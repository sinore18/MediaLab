import logging
from uuid import uuid4

from fastapi.testclient import TestClient

from server.api.v1.routes import downloads, uploads
from server.config import Settings
from server.main import app
from server.observability import LOG_FILE, configure_logging, log_exception
from server.services.processing.local_processing import ProcessedVideo

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_logging_level_tracks_environment() -> None:
    server_logger = logging.getLogger("server")
    uvicorn_error_logger = logging.getLogger("uvicorn.error")

    configure_logging(Settings(prod=True))
    assert server_logger.level == logging.CRITICAL
    assert uvicorn_error_logger.level == logging.CRITICAL

    configure_logging(Settings(prod=False))
    assert server_logger.level == logging.INFO
    assert uvicorn_error_logger.level == logging.INFO
    file_handlers = [handler for handler in server_logger.handlers if isinstance(handler, logging.FileHandler)]
    assert file_handlers
    assert file_handlers[0].level == logging.INFO
    assert logging.getLogger("numba").level == logging.WARNING
    assert logging.getLogger("server.services.processing.pipeline").level == logging.WARNING


def test_production_exception_log_includes_critical_level_and_traceback() -> None:
    from unittest.mock import Mock

    logger = Mock()
    configure_logging(Settings(prod=True))
    try:
        try:
            raise RuntimeError("diagnostic detail")
        except RuntimeError:
            log_exception(logger, "processing failed")

        assert logger.log.call_args.args[0] == logging.CRITICAL
        assert logger.log.call_args.kwargs["exc_info"] is True
    finally:
        configure_logging(Settings(prod=False))


def test_logs_are_appended_to_server_log_file() -> None:
    configure_logging(Settings(prod=False))
    logger = logging.getLogger("server.test_logging")
    marker = uuid4().hex
    first_entry = f"append-check-first-entry-{marker}"
    second_entry = f"append-check-second-entry-{marker}"
    propagated_entry = f"append-check-uvicorn-entry-{marker}"

    logger.info(first_entry)
    logging.getLogger("uvicorn.error").info(propagated_entry)
    configure_logging(Settings(prod=False))
    logger.info(second_entry)
    for handler in logging.getLogger("server").handlers:
        handler.flush()

    contents = LOG_FILE.read_text(encoding="utf-8")
    assert contents.index(first_entry) < contents.index(second_entry)
    assert propagated_entry in contents


def test_dev_http_error_reason_is_written_to_log_file() -> None:
    configure_logging(Settings(prod=False))
    response = client.post(
        "/api/v1/uploads/local",
        files={"file": ("notes.txt", b"not-video", "text/plain")},
    )

    assert response.status_code == 415
    for handler in logging.getLogger("server").handlers:
        handler.flush()
    assert "Only video files are accepted." in LOG_FILE.read_text(encoding="utf-8")


def test_upload_intent_rejects_oversized_video(monkeypatch) -> None:
    monkeypatch.setattr(uploads, "get_settings", lambda: Settings(prod=True))
    response = client.post(
        "/api/v1/uploads",
        json={
            "file_name": "large.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 501 * 1024 * 1024,
            "duration_seconds": 12,
        },
    )

    assert response.status_code == 413


def test_upload_intent_rejects_non_video_content_type() -> None:
    response = client.post(
        "/api/v1/uploads",
        json={
            "file_name": "notes.txt",
            "content_type": "text/plain",
            "file_size_bytes": 100,
            "duration_seconds": 1,
        },
    )

    assert response.status_code == 422


def test_download_intent_rejects_non_output_blob() -> None:
    response = client.post("/api/v1/downloads", json={"blob_name": "uploads/source.mp4"})

    assert response.status_code == 422


def test_upload_completion_rejects_non_upload_blob() -> None:
    response = client.post("/api/v1/uploads/complete", json={"blob_name": "outputs/result.mp4"})

    assert response.status_code == 422


def test_local_upload_returns_video_without_using_azure(monkeypatch) -> None:
    monkeypatch.setattr(uploads, "get_settings", lambda: Settings(prod=False))
    monkeypatch.setattr(uploads.MediaProbeService, "duration_seconds", lambda _self, _path: 12.5)

    class FakeLocalProcessor:
        def process(self, _video_path, output_path):
            output_path.write_bytes(b"processed-video")
            return ProcessedVideo(
                path=output_path,
                bleep_timestamps=(1.25, 4.5),
                bleep_spans=((1.25, 1.75), (4.5, 4.9)),
            )

    def fail_if_azure_is_used(*_args, **_kwargs):
        raise AssertionError("Azure must not be used in local mode")

    monkeypatch.setattr(uploads, "BlobStorageService", fail_if_azure_is_used)
    monkeypatch.setattr(uploads, "create_local_video_processor", lambda _settings: FakeLocalProcessor())
    response = client.post(
        "/api/v1/uploads/local",
        headers={"Origin": "http://localhost:3000"},
        files={"file": ("sample.mp4", b"video-bytes", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.content == b"processed-video"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["x-video-duration-seconds"] == "12.5"
    assert response.headers["x-bleep-timestamps"] == "[1.25,4.5]"
    assert response.headers["x-bleep-spans"] == "[[1.25,1.75],[4.5,4.9]]"
    assert "x-bleep-timestamps" in response.headers["access-control-expose-headers"].lower()
    assert "x-bleep-spans" in response.headers["access-control-expose-headers"].lower()
    assert response.headers["content-disposition"] == 'attachment; filename="bleeper-processed.mp4"'


def test_local_upload_route_is_disabled_when_prod_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(uploads, "get_settings", lambda: Settings(prod=True))
    response = client.post(
        "/api/v1/uploads/local",
        files={"file": ("sample.mp4", b"video-bytes", "video/mp4")},
    )

    assert response.status_code == 404


def test_azure_sas_routes_are_disabled_in_local_mode(monkeypatch) -> None:
    local_settings = lambda: Settings(prod=False)
    monkeypatch.setattr(uploads, "get_settings", local_settings)
    monkeypatch.setattr(downloads, "get_settings", local_settings)

    def fail_if_azure_is_used(*_args, **_kwargs):
        raise AssertionError("Azure must not be used in local mode")

    monkeypatch.setattr(uploads, "BlobStorageService", fail_if_azure_is_used)
    monkeypatch.setattr(downloads, "BlobStorageService", fail_if_azure_is_used)
    upload_response = client.post(
        "/api/v1/uploads",
        json={
            "file_name": "sample.mp4",
            "content_type": "video/mp4",
            "file_size_bytes": 100,
            "duration_seconds": 1,
        },
    )
    download_response = client.post(
        "/api/v1/downloads",
        json={"blob_name": "outputs/sample.mp4"},
    )

    assert upload_response.status_code == 404
    assert download_response.status_code == 404