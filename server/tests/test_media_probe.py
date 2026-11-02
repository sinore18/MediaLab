import json
from subprocess import CompletedProcess

from server.services.media.probe import MediaProbeService


def test_duration_uses_format_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "server.services.media.probe.subprocess.run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"format": {"duration": "4.2"}})
        ),
    )

    assert MediaProbeService().duration_seconds(tmp_path / "recording.webm") == 4.2


def test_duration_uses_stream_metadata_when_format_duration_is_unavailable(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "server.services.media.probe.subprocess.run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "format": {"duration": "N/A"},
                    "streams": [{"duration_ts": "48000", "time_base": "1/16000"}],
                }
            ),
        ),
    )

    assert MediaProbeService().duration_seconds(tmp_path / "recording.webm") == 3.0


def test_duration_uses_packet_timestamps_when_metadata_is_unavailable(
    monkeypatch, tmp_path
) -> None:
    outputs = iter(
        [
            json.dumps(
                {
                    "format": {"duration": "N/A"},
                    "streams": [{"duration": "N/A"}],
                }
            ),
            "0.000000,0.020000\n0.020000,0.020000\n1.980000,0.020000\n",
        ]
    )
    monkeypatch.setattr(
        "server.services.media.probe.subprocess.run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[], returncode=0, stdout=next(outputs)
        ),
    )

    assert MediaProbeService().duration_seconds(tmp_path / "recording.webm") == 2.0
