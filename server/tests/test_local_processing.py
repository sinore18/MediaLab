import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from server.config import Settings
from server.domain.schemas import ProfanitySpan, WordTiming
from server.services.processing import local_processing
from server.services.processing.local_aligner import LocalMMSWordAligner
from server.services.processing.local_processing import (
    GeminiProfanityDetector,
    LocalProcessingError,
    LocalVideoProcessor,
    LocalWhisperSpeechToText,
    VachanaSpeechToText,
)
from server.services.processing.pipeline import ProcessingPipeline


def test_local_whisper_transcriber_uses_configured_model(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.touch()

    class FakeModel:
        def transcribe(self, path: str, language: str, verbose: None):
            assert path == str(audio_path)
            assert language == "en"
            assert verbose is None
            return SimpleNamespace(text=" damn ")

    monkeypatch.setattr(
        local_processing, "_load_whisper_model", lambda model, device: FakeModel()
    )
    transcriber = LocalWhisperSpeechToText("tiny", "cpu", "en")

    caplog.set_level("INFO", logger=local_processing.__name__)
    assert transcriber.transcribe(audio_path) == "damn"
    assert 'provider=whisper transcript=" damn "' in caplog.text


def test_vachana_transcriber_sends_audio_and_uses_only_transcript(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"wav audio")
    captured = {}

    class FakeClient:
        def __init__(self, timeout: int):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, data, files, headers):
            captured.update(url=url, data=data, files=files, headers=headers)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "request_id": "req_abc123",
                    "timestamp": "20251226_143052.123",
                    "transcript": " नमस्ते ",
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)
    transcriber = VachanaSpeechToText("test-api-key-id")

    caplog.set_level("INFO", logger=local_processing.__name__)
    assert transcriber.transcribe(audio_path) == "नमस्ते"
    assert 'provider=vachana transcript=" नमस्ते "' in caplog.text
    assert captured["url"] == VachanaSpeechToText.endpoint
    assert captured["headers"]["X-API-Key-ID"] == "test-api-key-id"
    assert captured["timeout"] == 300
    assert captured["data"] == {
        "language_code": "indic-auto",
        "model": "prisma-v3.0",
        "format": "transcribe",
        "itn_native_numerals": "true",
        "enable_substitution": "true",
        "substitution_map": (
            '[{"patterns":["okay","ok"],"replacement":"acknowledged"},'
            '{"patterns":["rupees","rs"],"replacement":"INR"}]'
        ),
        "bias_list": '["Timbre","Prisma","EMI"]',
        "bias_score": "1",
    }
    assert captured["files"]["audio_file"] == ("speech.wav", b"wav audio", "audio/wav")

    verbatim_transcriber = VachanaSpeechToText(
        "test-api-key-id", language_code="hi-IN", use_domain_vocabulary=False
    )
    assert verbatim_transcriber.transcribe(audio_path) == "नमस्ते"
    assert captured["data"] == {
        "language_code": "hi-IN",
        "model": "prisma-v3.0",
        "format": "transcribe",
    }


def test_vachana_transcriber_rejects_unsuccessful_response(
    monkeypatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"wav audio")

    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"success": False},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)

    with pytest.raises(LocalProcessingError, match="unsuccessful"):
        VachanaSpeechToText("test-api-key-id").transcribe(audio_path)


@pytest.mark.parametrize("status_code", [401, 403])
def test_vachana_transcriber_reports_authorization_errors(
    monkeypatch,
    tmp_path: Path,
    status_code: int,
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"wav audio")

    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            return httpx.Response(status_code, text="", request=request)

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)

    with pytest.raises(LocalProcessingError, match="Vachana STT rejected the request"):
        VachanaSpeechToText("test-api-key-id").transcribe(audio_path)


def test_vachana_transcriber_includes_redacted_authorization_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"wav audio")
    api_key = "test-api-key-id"

    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return httpx.Response(
                403,
                json={"detail": f"Denied credential {api_key}"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)

    with pytest.raises(
        LocalProcessingError,
        match=r'Provider response: \{"detail":"Denied credential \[redacted\]"\}',
    ) as exc:
        VachanaSpeechToText(api_key).transcribe(audio_path)
    assert api_key not in str(exc.value)


def test_vachana_transcriber_trims_api_key_whitespace(
    monkeypatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"wav audio")
    captured = {}

    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, headers, **kwargs):
            captured["api_key"] = headers["X-API-Key-ID"]
            return httpx.Response(
                200,
                json={"success": True, "transcript": "hello"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)

    assert VachanaSpeechToText(" test-api-key-id ").transcribe(audio_path) == "hello"
    assert captured["api_key"] == "test-api-key-id"


def test_processor_factory_uses_vachana_stt_by_default() -> None:
    settings = Settings(
        stt_provider="Gnani",
        stt_language_code="hi-IN",
        stt_api_key=SecretStr("test-api-key-id"),
        gemini_api_key=SecretStr("test-gemini-api-key"),
    )

    processor = local_processing.create_local_video_processor(settings)

    assert isinstance(processor.pipeline.speech_to_text, VachanaSpeechToText)
    assert isinstance(processor.pipeline.word_aligner, LocalMMSWordAligner)
    assert processor.pipeline.word_aligner.language == "hin"
    assert isinstance(processor.pipeline.profanity_detector, GeminiProfanityDetector)
    assert processor.pipeline.profanity_detector.model_name == "gemini-3.5-flash-lite"


def test_local_video_processor_retains_extracted_audio(
    monkeypatch, tmp_path: Path
) -> None:
    audio_directory = tmp_path / "audio"
    monkeypatch.setattr(local_processing, "AUDIO_DIRECTORY", audio_directory)

    class FakeAudioExtractor:
        def extract(self, _video_path: Path, audio_path: Path) -> None:
            audio_path.write_bytes(b"original audio")

    class FakePipeline:
        def process(
            self, _video_path: Path, audio_path: Path, output_path: Path
        ) -> tuple[Path, tuple[tuple[float, float], ...]]:
            assert audio_path.read_bytes() == b"original audio"
            output_path.write_bytes(b"processed video")
            return output_path, ((0.2, 0.5), (1.4, 1.8))

    video_path = tmp_path / "source.mp4"
    video_path.touch()
    output_path = tmp_path / "processed.mp4"

    result = LocalVideoProcessor(FakePipeline(), FakeAudioExtractor()).process(
        video_path, output_path
    )

    retained_audio = list(audio_directory.glob("*.wav"))
    assert result.path == output_path
    assert result.bleep_timestamps == (0.2, 1.4)
    assert result.bleep_spans == ((0.2, 0.5), (1.4, 1.8))
    assert len(retained_audio) == 1
    assert retained_audio[0].read_bytes() == b"original audio"


def test_processing_pipeline_logs_each_step_as_it_completes(
    caplog, tmp_path: Path
) -> None:
    class FakeSpeechToText:
        def transcribe(self, _audio_path: Path) -> str:
            return "transcript"

    class FakeWordAligner:
        def align(self, _audio_path: Path, _transcript: str) -> list[WordTiming]:
            return []

    class FakeProfanityDetector:
        def find_matches(self, _words) -> list:
            return []

    class FakeRenderer:
        def render(self, _video_path: Path, _matches, output_path: Path) -> Path:
            output_path.write_bytes(b"processed")
            return output_path

    pipeline = ProcessingPipeline(
        speech_to_text=FakeSpeechToText(),
        word_aligner=FakeWordAligner(),
        profanity_detector=FakeProfanityDetector(),
        renderer=FakeRenderer(),
    )
    caplog.set_level("INFO", logger="server.services.processing.pipeline")

    pipeline.process(
        tmp_path / "source.mp4", tmp_path / "audio.wav", tmp_path / "output.mp4"
    )

    completed_steps = [
        record.getMessage()
        for record in caplog.records
        if "processing step completed" in record.getMessage()
    ]
    assert [message.split("step=")[1].split()[0] for message in completed_steps] == [
        "transcription",
        "word_alignment",
        "profanity_detection",
        "rendering",
    ]


def test_gemini_profanity_detector_maps_standardized_word_and_phrase_spans(
    monkeypatch,
) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, timeout: int):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": (
                                            '{"profanity_spans":['
                                            '{"start_index":0,"end_index":0,"type":"word"},'
                                            '{"start_index":1,"end_index":2,"type":"phrase"}]}'
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)
    detector = GeminiProfanityDetector("test-gemini-key")
    timings = [
        WordTiming(word="That", start_seconds=0.1, end_seconds=0.2),
        WordTiming(word="was", start_seconds=0.2, end_seconds=0.3),
        WordTiming(word="awful!", start_seconds=0.3, end_seconds=0.6),
    ]

    matches = detector.find_matches(timings)

    assert matches[0].word == "That"
    assert matches[0].kind == "word"
    assert matches[0].start_seconds == 0.1
    assert matches[1].word == "was awful!"
    assert matches[1].kind == "phrase"
    assert matches[1].start_seconds == 0.2
    assert matches[1].end_seconds == 0.6
    assert captured["url"].endswith("/gemini-3.5-flash-lite:generateContent")
    assert captured["headers"] == {"x-goog-api-key": "test-gemini-key"}
    assert captured["timeout"] == 60
    assert (
        'Transcript tokens (JSON array): ["That", "was", "awful!"]'
        in (captured["json"]["contents"][0]["parts"][0]["text"])
    )
    schema = captured["json"]["generationConfig"]["responseSchema"]
    assert schema["required"] == ["profanity_spans"]
    assert schema["properties"]["profanity_spans"]["items"]["required"] == [
        "start_index",
        "end_index",
        "type",
    ]


@pytest.mark.parametrize(
    ("response_text", "error"),
    [
        (
            '{"profanity_spans":[{"start_index":4,"end_index":4,"type":"word"}]}',
            "out-of-range",
        ),
        (
            '{"profanity_spans":[{"start_index":0,"end_index":1,"type":"sentence"}]}',
            "invalid profanity span type",
        ),
    ],
)
def test_gemini_profanity_detector_rejects_invalid_spans(
    monkeypatch, response_text: str, error: str
) -> None:
    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": response_text}]}}]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)
    detector = GeminiProfanityDetector("test-gemini-key")

    with pytest.raises(LocalProcessingError, match=error):
        detector.find_matches(
            [
                WordTiming(word="hello", start_seconds=0.0, end_seconds=0.5),
                WordTiming(word="world", start_seconds=0.5, end_seconds=1.0),
            ]
        )


def test_gemini_profanity_detector_merges_overlapping_spans(monkeypatch) -> None:
    response_text = (
        '{"profanity_spans":['
        '{"start_index":2,"end_index":2,"type":"phrase"},'
        '{"start_index":0,"end_index":1,"type":"word"},'
        '{"start_index":1,"end_index":2,"type":"phrase"},'
        '{"start_index":3,"end_index":3,"type":"word"}]}'
    )

    class FakeClient:
        def __init__(self, timeout: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": response_text}]}}]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(local_processing.httpx, "Client", FakeClient)
    detector = GeminiProfanityDetector("test-gemini-key")
    timings = [
        WordTiming(word="one", start_seconds=0.0, end_seconds=0.2),
        WordTiming(word="two", start_seconds=0.2, end_seconds=0.4),
        WordTiming(word="three", start_seconds=0.4, end_seconds=0.6),
        WordTiming(word="four", start_seconds=0.6, end_seconds=0.8),
    ]

    matches = detector.find_matches(timings)

    assert [(match.word, match.kind) for match in matches] == [
        ("one two three", "phrase"),
        ("four", "word"),
    ]
    assert [(match.start_seconds, match.end_seconds) for match in matches] == [
        (0.0, 0.6),
        (0.6, 0.8),
    ]


def test_phrase_match_is_rendered_as_one_continuous_bleep(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run_ffmpeg(arguments, step):
        captured.update(arguments=arguments, step=step)

    monkeypatch.setattr(local_processing, "_run_ffmpeg", fake_run_ffmpeg)
    renderer = local_processing.FfmpegBleepRenderer()
    renderer.render(
        tmp_path / "source.mp4",
        [
            ProfanitySpan(
                word="phrase words",
                start_seconds=0.2,
                end_seconds=1.1,
                kind="phrase",
            )
        ],
        tmp_path / "output.mp4",
    )

    filter_complex = captured["arguments"][
        captured["arguments"].index("-filter_complex") + 1
    ]
    assert filter_complex.count("sine=frequency=1000") == 1
    assert "between(t,0.200,1.100)" in filter_complex
    assert "duration=0.900000" in filter_complex


def test_gemini_profanity_detector_requires_api_key() -> None:
    with pytest.raises(LocalProcessingError, match="GEMINI_API_KEY"):
        GeminiProfanityDetector("")


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is required for local video processing",
)
def test_local_video_processor_generates_cleaned_video(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(local_processing, "AUDIO_DIRECTORY", tmp_path / "audio")
    source_path = tmp_path / "source.mp4"
    output_path = tmp_path / "processed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:r=15:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )

    class FakeSpeechToText:
        def transcribe(self, audio_path: Path) -> str:
            assert audio_path.is_file()
            return "damn"

    class FakeWordAligner:
        def align(self, _audio_path: Path, transcript: str) -> list[WordTiming]:
            assert transcript == "damn"
            return [WordTiming(word="damn", start_seconds=0.2, end_seconds=0.5)]

    class FakeProfanityDetector:
        def find_matches(self, words):
            return []

    pipeline = ProcessingPipeline(
        speech_to_text=FakeSpeechToText(),
        word_aligner=FakeWordAligner(),
        profanity_detector=FakeProfanityDetector(),
        renderer=local_processing.FfmpegBleepRenderer(),
    )
    result = LocalVideoProcessor(pipeline).process(source_path, output_path)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(result.path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.path == output_path
    assert result.path.stat().st_size > 0
    assert result.bleep_timestamps == ()
    assert result.bleep_spans == ()
    assert probe.stdout.strip() == "h264"
