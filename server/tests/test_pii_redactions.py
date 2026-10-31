import hashlib
import io
import json
import zipfile

from fastapi.testclient import TestClient

from server.api.v1.routes import pii_redactions
from server.config import Settings
from server.domain.schemas import WordTiming
from server.main import app

client = TestClient(app)
_SYNTHETIC_CARD = "7992739871300"
_SPOKEN_CARD = "seven nine nine two seven three nine eight seven one three zero zero"


def test_pii_redactions_route_returns_audio_transcript_and_metadata_audit(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(pii_redactions, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        pii_redactions.MediaProbeService,
        "duration_seconds",
        lambda _self, _path: 3.0,
    )

    class FakeAudioExtractor:
        def extract(self, source_path, output_path) -> None:
            assert source_path.read_bytes() == b"synthetic-original-audio"
            output_path.write_bytes(b"synthetic-normalized-audio")

    class FakeSpeechToText:
        def transcribe(self, audio_path) -> str:
            content = audio_path.read_bytes()
            stt_calls.append(content)
            if content == b"synthetic-normalized-audio":
                return _SPOKEN_CARD
            assert content == b"synthetic-redacted-audio"
            return ""

    class FakeWordAligner:
        def align(self, _audio_path, transcript: str) -> list[WordTiming]:
            if not transcript:
                return []
            assert transcript == _SPOKEN_CARD
            return [
                WordTiming(
                    word=word,
                    start_seconds=index * 0.1,
                    end_seconds=(index + 1) * 0.1,
                )
                for index, word in enumerate(transcript.split())
            ]

    class FakeRenderer:
        def render_audio(self, _audio_path, spans, output_path, *, duration_seconds):
            assert duration_seconds == 3.0
            assert [span.category for span in spans] == ["CARD"]
            output_path.write_bytes(b"synthetic-redacted-audio")
            return output_path

    provider_kwargs = {}
    stt_calls = []
    monkeypatch.setattr(
        pii_redactions,
        "FfmpegAudioExtractor",
        FakeAudioExtractor,
    )
    monkeypatch.setattr(
        pii_redactions,
        "create_speech_to_text_provider",
        lambda _settings, **kwargs: (
            provider_kwargs.update(kwargs) or FakeSpeechToText()
        ),
    )
    monkeypatch.setattr(
        pii_redactions,
        "create_word_aligner",
        lambda *_args, **_kwargs: FakeWordAligner(),
    )
    monkeypatch.setattr(pii_redactions, "FfmpegBleepRenderer", FakeRenderer)

    response = client.post(
        "/api/v1/pii-redactions",
        files={"file": ("sample.wav", b"synthetic-original-audio", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "/api/v1/pii-redactions" in app.openapi()["paths"]
    assert provider_kwargs == {
        "language_code": "indic-auto",
        "use_domain_vocabulary": False,
        "log_transcript": False,
    }
    assert stt_calls == [
        b"synthetic-normalized-audio",
        b"synthetic-redacted-audio",
    ]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "redacted_audio.wav",
            "redacted_transcript.txt",
            "audit.json",
        ]
        redacted_audio = archive.read("redacted_audio.wav")
        transcript = archive.read("redacted_transcript.txt").decode("utf-8")
        audit_text = archive.read("audit.json").decode("utf-8")
        audit = json.loads(audit_text)

    assert redacted_audio == b"synthetic-redacted-audio"
    assert transcript == "[CARD]"
    assert audit == {
        "original_sha256": hashlib.sha256(b"synthetic-original-audio").hexdigest(),
        "detections": [
            {
                "category": "CARD",
                "start": 0.0,
                "end": 1.3,
                "confidence": 0.99,
                "validator_result": True,
            }
        ],
        "verification": {
            "leaked_items": [],
            "pii_recall": 1.0,
            "seconds_over_redacted": 0.08,
        },
    }
    assert _SYNTHETIC_CARD not in transcript
    assert _SYNTHETIC_CARD not in audit_text
    assert _SYNTHETIC_CARD not in redacted_audio.decode("utf-8", errors="ignore")
    assert _SYNTHETIC_CARD not in caplog.text


def test_pii_redactions_rejects_non_audio_upload() -> None:
    response = client.post(
        "/api/v1/pii-redactions",
        files={"file": ("sample.txt", b"synthetic-not-audio", "text/plain")},
    )

    assert response.status_code == 415
