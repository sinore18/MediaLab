from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from server.domain.schemas import AlignedWord, DetectionSpan, ProfanitySpan, WordTiming


class SpeechToTextProvider(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class WordAligner(Protocol):
    def align(self, audio_path: Path, transcript: str) -> Sequence[WordTiming]: ...


class ProfanityDetector(Protocol):
    def find_matches(self, words: Sequence[WordTiming]) -> Sequence[ProfanitySpan]: ...


@runtime_checkable
class DetectorPlugin(Protocol):
    def detect(self, words: Sequence[AlignedWord]) -> Sequence[DetectionSpan]: ...


class BleepRenderer(Protocol):
    def render(self, video_path: Path, matches: Sequence[ProfanitySpan], output_path: Path) -> Path: ...