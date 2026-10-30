import logging
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from server.domain.schemas import ProfanitySpan, WordTiming
from server.services.processing import local_aligner
from server.services.processing.local_aligner import (
    LocalAlignmentError,
    LocalMMSWordAligner,
)
from server.services.processing.pipeline import ProcessingPipeline


class FakeWaveform:
    ndim = 2

    def __init__(self, samples: int = 32000) -> None:
        self.samples = samples

    def size(self, dimension: int) -> int:
        return 1 if dimension == 0 else self.samples

    def mean(self, dim: int, keepdim: bool):
        assert dim == 0
        assert keepdim
        return self

    def unsqueeze(self, dim: int):
        assert dim == 0
        return self

    def to(self, device: str):
        assert device == "cpu"
        return self


class FakeEmission:
    def size(self, dimension: int) -> int:
        return (1, 100, 28)[dimension]

    def __getitem__(self, index: int):
        assert index == 0
        return self


def _install_fake_audio_modules(monkeypatch, audio: FakeWaveform) -> None:
    torch = ModuleType("torch")
    torch.inference_mode = nullcontext
    torch.float32 = "float32"
    torch.frombuffer = lambda data, dtype: audio
    torchaudio = ModuleType("torchaudio")
    torchaudio.pipelines = SimpleNamespace(MMS_FA=SimpleNamespace(sample_rate=16000))
    torchaudio.functional = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)
    monkeypatch.setattr(
        local_aligner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"\x00\x00\x00\x00"),
    )


def test_mms_aligner_returns_word_timestamps_from_second_pass(monkeypatch) -> None:
    waveform = FakeWaveform()
    _install_fake_audio_modules(monkeypatch, waveform)

    class Model:
        def __call__(self, audio):
            assert audio is waveform
            return FakeEmission(), None

    class Tokenizer:
        def __call__(self, words: list[str]) -> list[list[int]]:
            assert words == ["hello", "world"]
            return [[1, 2], [3, 4]]

    class Aligner:
        def __call__(self, emission, tokens):
            assert isinstance(emission, FakeEmission)
            assert tokens == [[1, 2], [3, 4]]
            return [
                [SimpleNamespace(start=0, end=25)],
                [SimpleNamespace(start=30, end=55)],
            ]

    class Romanizer:
        def romanize_string(self, word: str, lcode: str | None):
            assert lcode == "eng"
            return word

    aligner = LocalMMSWordAligner()
    aligner._components = (Model(), Tokenizer(), Aligner(), Romanizer())

    timings = aligner.align(Path("speech.wav"), "hello world!")

    assert timings == [
        WordTiming(word="hello", start_seconds=0.0, end_seconds=0.5),
        WordTiming(word="world!", start_seconds=0.6, end_seconds=1.1),
    ]


def test_mms_aligner_romanizes_hindi_transcript(monkeypatch) -> None:
    _install_fake_audio_modules(monkeypatch, FakeWaveform())
    romanizer_calls = []

    class Model:
        def __call__(self, audio):
            return FakeEmission(), None

    class Tokenizer:
        def __call__(self, words: list[str]) -> list[list[int]]:
            assert words == ["namaste"]
            return [[1]]

    class Aligner:
        def __call__(self, emission, tokens):
            return [[SimpleNamespace(start=4, end=20)]]

    class Romanizer:
        def romanize_string(self, word: str, lcode: str | None):
            romanizer_calls.append((word, lcode))
            return "namaste"

    aligner = LocalMMSWordAligner(language="hi-IN")
    aligner._components = (Model(), Tokenizer(), Aligner(), Romanizer())

    timings = aligner.align(Path("speech.wav"), "नमस्ते")

    assert romanizer_calls == [("नमस्ते", "hin")]
    assert timings == [WordTiming(word="नमस्ते", start_seconds=0.08, end_seconds=0.4)]


def test_mms_aligner_rejects_empty_token_sequences(monkeypatch) -> None:
    _install_fake_audio_modules(monkeypatch, FakeWaveform())

    class Model:
        def __call__(self, audio):
            return FakeEmission(), None

    class Tokenizer:
        def __call__(self, words: list[str]) -> list[list[int]]:
            return [[] for _ in words]

    class Romanizer:
        def romanize_string(self, word: str, lcode: str | None):
            return word

    aligner = LocalMMSWordAligner()
    aligner._components = (Model(), Tokenizer(), object(), Romanizer())

    with pytest.raises(LocalAlignmentError, match="could not tokenize"):
        aligner.align(Path("speech.wav"), "hello")


def test_processing_pipeline_defaults_to_local_aligner() -> None:
    pipeline = ProcessingPipeline(
        speech_to_text=object(),
        profanity_detector=object(),
        renderer=object(),
    )

    assert isinstance(pipeline.word_aligner, LocalMMSWordAligner)


def test_processing_pipeline_does_not_log_word_timestamps(caplog) -> None:
    class SpeechToText:
        def transcribe(self, audio_path: Path) -> str:
            return "hello"

    class WordAligner:
        def align(self, audio_path: Path, transcript: str) -> list[WordTiming]:
            return [WordTiming(word="hello", start_seconds=0.01, end_seconds=0.5)]

    class ProfanityDetector:
        def find_matches(self, words):
            return [ProfanitySpan(word="hello", start_seconds=0.01, end_seconds=0.5)]

    class Renderer:
        def render(self, video_path: Path, matches, output_path: Path) -> Path:
            return output_path

    pipeline = ProcessingPipeline(
        speech_to_text=SpeechToText(),
        word_aligner=WordAligner(),
        profanity_detector=ProfanityDetector(),
        renderer=Renderer(),
    )

    with caplog.at_level(logging.INFO, logger="server.services.processing.pipeline"):
        _, spans = pipeline.process(
            Path("video.mp4"), Path("speech.wav"), Path("output.mp4")
        )

    assert spans == ((0.01, 0.5),)
    assert '"hello": 0.010-0.500' not in caplog.text
    assert (
        'profanity identified kind=word text="hello" start_seconds=0.010 end_seconds=0.500'
        in caplog.text
    )
