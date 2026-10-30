from fastapi.testclient import TestClient

from server.api.v1.routes import transcriptions
from server.config import Settings
from server.domain.schemas import WordTiming
from server.main import app

client = TestClient(app)


def test_audio_transcription_returns_aligned_words(monkeypatch) -> None:
    monkeypatch.setattr(
        transcriptions, "get_settings", lambda: Settings(stt_provider="gnani")
    )
    monkeypatch.setattr(
        transcriptions.MediaProbeService, "duration_seconds", lambda _self, _path: 4.2
    )
    extracted_paths = []
    requested_languages = []

    class FakeAudioExtractor:
        def extract(self, source_path, output_path):
            assert source_path.read_bytes() == b"audio-bytes"
            output_path.write_bytes(b"normalized-wav")
            extracted_paths.append(output_path)

    class FakeSpeechToText:
        def transcribe(self, audio_path):
            assert audio_path.read_bytes() == b"normalized-wav"
            return "Hello there."

    class FakeWordAligner:
        def align(self, audio_path, transcript):
            assert audio_path.read_bytes() == b"normalized-wav"
            assert transcript == "Hello there."
            return [
                WordTiming(word="Hello", start_seconds=0.1, end_seconds=0.6),
                WordTiming(word="there.", start_seconds=0.7, end_seconds=1.1),
            ]

    monkeypatch.setattr(
        transcriptions,
        "create_speech_to_text_provider",
        lambda _settings, language_code, use_domain_vocabulary: (
            requested_languages.append((language_code, use_domain_vocabulary))
            or FakeSpeechToText()
        ),
    )
    monkeypatch.setattr(
        transcriptions,
        "create_word_aligner",
        lambda _settings, language_code: (
            requested_languages.append(language_code) or FakeWordAligner()
        ),
    )
    monkeypatch.setattr(transcriptions, "FfmpegAudioExtractor", FakeAudioExtractor)

    response = client.post(
        "/api/v1/transcriptions",
        data={"language_code": "hi-IN"},
        files={"file": ("sample.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "transcript": "Hello there.",
        "duration_seconds": 4.2,
        "words": [
            {"word": "Hello", "start_seconds": 0.1, "end_seconds": 0.6},
            {"word": "there.", "start_seconds": 0.7, "end_seconds": 1.1},
        ],
    }
    assert extracted_paths[0].suffix == ".wav"
    assert requested_languages == [("indic-auto", False), "indic-auto"]


def test_audio_transcription_rejects_non_audio_files() -> None:
    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("notes.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 415


def test_audio_transcription_rejects_files_over_configured_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        transcriptions,
        "get_settings",
        lambda: Settings(stt_provider="gnani", max_upload_size_mb=1),
    )

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("large.wav", b"x" * (1024 * 1024 + 1), "audio/wav")},
    )

    assert response.status_code == 413


def test_audio_transcription_rejects_local_whisper_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        transcriptions,
        "get_settings",
        lambda: Settings(stt_provider="local"),
    )

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("sample.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 503
