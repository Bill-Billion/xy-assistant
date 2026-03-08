from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.command_service import CommandService
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.services.llm_client import DoubaoClient
from app.services.weather_broadcast import WeatherBroadcastGenerator
from app.services.weather_client import WeatherClient, WeatherClientConfig
from app.services.weather_service import WeatherService


@lru_cache(maxsize=1)
def get_conversation_manager() -> ConversationManager:
    return ConversationManager()


@lru_cache(maxsize=1)
def get_llm_client() -> DoubaoClient:
    settings = get_settings()
    return DoubaoClient(
        api_key=settings.doubao_api_key,
        api_url=settings.doubao_api_url,
        model=settings.doubao_model,
        timeout=settings.doubao_timeout,
        max_tokens=settings.doubao_max_tokens,
        temperature=settings.doubao_temperature,
        top_p=settings.doubao_top_p,
        stop_words=settings.doubao_stop_words,
    )


@lru_cache(maxsize=1)
def get_intent_classifier() -> IntentClassifier:
    settings = get_settings()
    return IntentClassifier(
        llm_client=get_llm_client(),
        confidence_threshold=settings.confidence_threshold,
    )


@lru_cache(maxsize=1)
def get_weather_service() -> WeatherService:
    settings = get_settings()
    if not settings.weather_api_enabled or not settings.weather_api_app_code:
        llm_client = get_llm_client() if settings.weather_llm_enabled else None
        return WeatherService(settings, client=None, llm_client=llm_client)
    client = WeatherClient(
        WeatherClientConfig(
            app_code=settings.weather_api_app_code,
            base_url=settings.weather_api_base_url,
            timeout=settings.weather_api_timeout,
            verify_ssl=settings.weather_api_verify_ssl,
        )
    )
    llm_client = get_llm_client() if settings.weather_llm_enabled else None
    return WeatherService(settings, client=client, llm_client=llm_client)


@lru_cache(maxsize=1)
def get_weather_broadcast_generator() -> WeatherBroadcastGenerator:
    settings = get_settings()
    llm_client = get_llm_client() if settings.weather_broadcast_llm_enabled else None
    return WeatherBroadcastGenerator(
        llm_client,
        enabled=settings.weather_broadcast_llm_enabled,
        cache_ttl=settings.weather_cache_ttl,
        max_tokens_override=settings.weather_broadcast_max_tokens,
    )


def get_command_service() -> CommandService:
    settings = get_settings()
    return CommandService(
        intent_classifier=get_intent_classifier(),
        conversation_manager=get_conversation_manager(),
        settings=settings,
        weather_service=get_weather_service(),
        weather_broadcast_generator=get_weather_broadcast_generator(),
        reply_llm_client=get_llm_client(),
    )
