import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from server.api.v1.routes import uploads
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
        "/api/v1/uploads",
        files={"file": ("notes.txt", b"not-video", "text/plain")},
    )

    assert response.status_code == 415
    for handler in logging.getLogger("server").handlers:
        handler.flush()
    assert "Only video files are accepted." in LOG_FILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("prod", [False, True])
def test_upload_returns_processed_video_in_every_environment(monkeypatch, prod: bool) -> None:
    monkeypatch.setattr(uploads, "get_settings", lambda: Settings(prod=prod))
    monkeypatch.setattr(uploads.MediaProbeService, "duration_seconds", lambda _self, _path: 12.5)

    class FakeLocalProcessor:
        def process(self, _video_path, output_path):
            output_path.write_bytes(b"processed-video")
            return ProcessedVideo(
                path=output_path,
                bleep_timestamps=(1.25, 4.5),
                bleep_spans=((1.25, 1.75), (4.5, 4.9)),
            )

    monkeypatch.setattr(uploads, "create_local_video_processor", lambda _settings: FakeLocalProcessor())
    response = client.post(
        "/api/v1/uploads",
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


def test_blob_storage_routes_are_removed() -> None:
    upload_completion_response = client.post(
        "/api/v1/uploads/complete", json={"blob_name": "uploads/sample.mp4"}
    )
    download_response = client.post(
        "/api/v1/downloads", json={"blob_name": "outputs/sample.mp4"}
    )

    assert upload_completion_response.status_code == 404
    assert download_response.status_code == 404