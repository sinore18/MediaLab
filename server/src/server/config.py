from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    prod: bool = False
    environment: str = "development"
    cors_origins: str = "http://localhost:3000"
    max_upload_size_mb: int = 500
    max_video_duration_seconds: int = 600
    max_audio_duration_seconds: int = 600
    azure_storage_account_name: str = ""
    azure_storage_account_key: SecretStr = SecretStr("")
    azure_storage_container: str = "bleeper-media"
    azure_sas_expiry_minutes: int = 15
    stt_provider: str = "vachana"
    stt_api_key: SecretStr = SecretStr("")
    stt_language_code: str = "indic-auto"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    local_stt_model: str = "base"
    local_stt_device: str = "cpu"
    local_stt_language: str = "en"
    local_alignment_device: str = "cpu"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def blob_storage_configured(self) -> bool:
        return bool(self.azure_storage_account_name and self.azure_storage_account_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()