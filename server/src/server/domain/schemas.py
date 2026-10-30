from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class UploadRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    file_size_bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)

    @field_validator("content_type")
    @classmethod
    def require_video_content_type(cls, value: str) -> str:
        if not value.lower().startswith("video/"):
            raise ValueError("Only video files are accepted")
        return value


class UploadGrant(BaseModel):
    blob_name: str
    upload_url: str
    expires_at: datetime


class UploadCompleteRequest(BaseModel):
    blob_name: str = Field(min_length=1, max_length=512)

    @field_validator("blob_name")
    @classmethod
    def require_upload_blob(cls, value: str) -> str:
        if not value.startswith("uploads/") or ".." in value.split("/"):
            raise ValueError("Only uploaded source videos can be finalized")
        return value


class UploadCompleteResponse(BaseModel):
    blob_name: str
    duration_seconds: float
    status: str = "accepted"


class DownloadRequest(BaseModel):
    blob_name: str = Field(min_length=1, max_length=512)

    @field_validator("blob_name")
    @classmethod
    def require_output_blob(cls, value: str) -> str:
        if not value.startswith("outputs/") or ".." in value.split("/"):
            raise ValueError("Only processed output videos can be downloaded")
        return value


class DownloadGrant(BaseModel):
    download_url: str
    expires_at: datetime


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
