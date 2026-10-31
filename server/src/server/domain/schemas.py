from typing import Literal

from pydantic import BaseModel, Field


class AlignedWord(BaseModel):
    """Word timing passed to detector plugins."""

    word: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    conf: float | None = Field(default=None, ge=0, le=1)
    approximate: bool = False


class DetectionSpan(BaseModel):
    """A detector result mapped to inclusive aligned-word indexes."""

    category: str
    first_word_idx: int = Field(ge=0)
    last_word_idx: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    validator_result: bool | None = None


class WordTiming(BaseModel):
    word: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    approximate: bool = False


class TranscriptionResponse(BaseModel):
    transcript: str
    duration_seconds: float = Field(gt=0)
    words: list[WordTiming]


class ProfanitySpan(BaseModel):
    word: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    kind: Literal["word", "phrase"] = "word"
