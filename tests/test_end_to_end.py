import pytest

from app.core.config import Settings
from app.schemas.request import CommandRequest
from app.services.command_service import CommandService
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier


class SequencedFakeDoubao:
    def __init__(self, payloads):
        self._payloads = list(payloads)

    async def chat(self, system_prompt, messages, response_format=None):  # noqa: D401
        if not self._payloads:
            raise RuntimeError("no payload available")
        payload = self._payloads.pop(0)
        return (payload.get("raw", ""), payload)


@pytest.mark.asyncio
async def test_end_to_end_clarify_then_confirm(monkeypatch):
    fake_llm = SequencedFakeDoubao(
        [
            {
                "intent_code": "UNKNOWN",
                "confidence": 0.3,
                "need_clarify": True,
                "clarify_message": "您是想听戏曲还是听音乐呢？",
                "reply": "您是想听戏曲还是听音乐呢？",
            },
            {
                "intent_code": "ENTERTAINMENT_OPERA_SPECIFIC",
                "result": "想听京剧",
                "target": "京剧",
                "confidence": 0.88,
                "reply": "好的，为您播放京剧。",
            },
        ]
    )

    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    manager = ConversationManager()
    settings = Settings(
        DOUBAO_API_KEY="test",
        DOUBAO_MODEL="test-model",
        DOUBAO_API_URL="https://example.com",
        DOUBAO_TIMEOUT=5.0,
        CONFIDENCE_THRESHOLD=0.7,
        ENVIRONMENT="test",
    )
    service = CommandService(classifier, manager, settings)

    first_response = await service.handle_command(
        CommandRequest(sessionId="sess-1", query="我想娱乐一下")
    )
    assert first_response.function_analysis.need_clarify is True
    assert "听戏曲还是听音乐" in (first_response.function_analysis.clarify_message or "")

    second_response = await service.handle_command(
        CommandRequest(sessionId="sess-1", query="听京剧吧")
    )
    assert second_response.function_analysis.result == "小雅曲艺"
    assert second_response.function_analysis.target == "京剧"
    assert second_response.function_analysis.need_clarify is False
