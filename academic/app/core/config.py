from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    doubao_api_key: str = Field(..., alias="DOUBAO_API_KEY")
    doubao_api_url: str = Field(
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        alias="DOUBAO_API_URL",
    )
    doubao_model: str = Field(..., alias="DOUBAO_MODEL")
    doubao_timeout: float = Field(10.0, alias="DOUBAO_TIMEOUT")
    confidence_threshold: float = Field(0.7, alias="CONFIDENCE_THRESHOLD")
    environment: Literal["dev", "prod", "test"] = Field("dev", alias="ENVIRONMENT")

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
