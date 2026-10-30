from typing import Literal

from pydantic import BaseModel, Field


class WordTiming(BaseModel):
    word: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class TranscriptionResponse(BaseModel):
    transcript: str
    duration_seconds: float = Field(gt=0)
    words: list[WordTiming]


class ProfanitySpan(BaseModel):
    word: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    kind: Literal["word", "phrase"] = "word"
