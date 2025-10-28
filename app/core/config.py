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
    weather_api_enabled: bool = Field(True, alias="WEATHER_API_ENABLED")
    weather_api_app_code: str | None = Field(None, alias="WEATHER_API_APP_CODE")
    weather_api_base_url: str = Field("https://ali-weather.showapi.com", alias="WEATHER_API_BASE_URL")
    weather_api_timeout: float = Field(5.0, alias="WEATHER_API_TIMEOUT")
    weather_api_verify_ssl: bool = Field(False, alias="WEATHER_API_VERIFY_SSL")
    weather_default_city: str = Field("长沙市", alias="WEATHER_DEFAULT_CITY")
    weather_default_lat: float = Field(28.22778, alias="WEATHER_DEFAULT_LAT")
    weather_default_lon: float = Field(112.93886, alias="WEATHER_DEFAULT_LON")
    weather_cache_ttl: int = Field(600, alias="WEATHER_CACHE_TTL")
    weather_geo_cache_ttl: int = Field(86400, alias="WEATHER_GEO_CACHE_TTL")
    weather_llm_enabled: bool = Field(True, alias="WEATHER_LLM_ENABLED")
    weather_llm_confidence_threshold: float = Field(0.6, alias="WEATHER_LLM_CONFIDENCE_THRESHOLD")
    weather_llm_low_confidence_threshold: float = Field(0.3, alias="WEATHER_LLM_LOW_CONFIDENCE_THRESHOLD")
    weather_broadcast_llm_enabled: bool = Field(True, alias="WEATHER_BROADCAST_LLM_ENABLED")

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
