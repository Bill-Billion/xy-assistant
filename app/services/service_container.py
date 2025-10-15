from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.command_service import CommandService
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.services.llm_client import DoubaoClient


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
    )


@lru_cache(maxsize=1)
def get_intent_classifier() -> IntentClassifier:
    settings = get_settings()
    return IntentClassifier(
        llm_client=get_llm_client(),
        confidence_threshold=settings.confidence_threshold,
    )


def get_command_service() -> CommandService:
    settings = get_settings()
    return CommandService(
        intent_classifier=get_intent_classifier(),
        conversation_manager=get_conversation_manager(),
        settings=settings,
    )
