from datetime import datetime
import pytest

from app.core.config import Settings
from app.schemas.request import CommandRequest
from app.services.command_service import CommandService
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.utils.time_utils import EAST_EIGHT


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
    assert first_response.requires_selection is True

    second_response = await service.handle_command(
        CommandRequest(sessionId="sess-1", query="听京剧吧")
    )
    assert second_response.function_analysis.result == "小雅曲艺"
    assert second_response.function_analysis.target == "京剧"
    assert second_response.function_analysis.need_clarify is False
    assert second_response.requires_selection is False


@pytest.mark.asyncio
async def test_command_service_merges_advice_into_msg():
    fake_llm = SequencedFakeDoubao(
        [
            {
                "intent_code": "UNKNOWN",
                "advice": "建议先适当休息，观察头晕情况。",
                "safety_notice": "小雅的建议仅供参考，如症状持续请及时咨询医生。",
                "clarify_message": "需要我为您提供更多健康建议还是帮您联系医生咨询呢？",
                "need_clarify": True,
                "confidence": 0.6,
            }
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

    response = await service.handle_command(
        CommandRequest(sessionId="sess-2", query="我有点头疼")
    )

    assert response.function_analysis.advice is not None
    assert response.function_analysis.safety_notice is not None
    assert response.function_analysis.need_clarify is True
    assert response.msg == "建议先适当休息，观察头晕情况。 小雅的建议仅供参考，如症状持续请及时咨询医生。 需要我为您提供更多健康建议还是帮您联系医生咨询呢？"
    assert response.requires_selection is True


@pytest.mark.asyncio
async def test_alarm_template_message(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "ALARM_CREATE",
            "result": "新增闹钟",
            "target": "2024-09-20 18-00-00",
            "event": None,
            "status": None,
            "confidence": 0.95,
            "reply": "已经设置。",
        }
    ])
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
    from app.services import command_service as cs_module
    from app.utils.time_utils import EAST_EIGHT
    fake_now = datetime(2024, 9, 20, 10, 0, tzinfo=EAST_EIGHT)
    monkeypatch.setattr(cs_module, "now_e8", lambda: fake_now)
    response = await service.handle_command(
        CommandRequest(sessionId="sess-alarm", query="帮我订个6点的闹钟")
    )
    assert response.msg == "好的，我已为您设置今天18:00的闹钟。"
    assert response.requires_selection is False


@pytest.mark.asyncio
async def test_close_music_template_message():
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "ENTERTAINMENT_MUSIC_OFF",
            "result": "关闭音乐",
            "target": "",
            "confidence": 0.9,
            "reply": "正在关闭音乐。",
        }
    ])
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
    response = await service.handle_command(
        CommandRequest(sessionId="sess-close", query="关闭音乐")
    )
    assert response.msg == "好的，正在关闭音乐。"


@pytest.mark.asyncio
async def test_alarm_tomorrow_morning_message(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "ALARM_REMINDER",
            "result": "新增闹钟",
            "target": "2024-09-21 09-00-00",
            "event": "吃药",
            "status": None,
            "confidence": 0.95,
            "reply": "好的",
        }
    ])
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
    from app.services import command_service as cs_module
    from app.utils.time_utils import EAST_EIGHT
    fake_now = datetime(2024, 9, 20, 10, 0, tzinfo=EAST_EIGHT)
    monkeypatch.setattr(cs_module, "now_e8", lambda: fake_now)
    response = await service.handle_command(
        CommandRequest(sessionId="sess-alarm-2", query="明早9点提醒我吃药")
    )
    assert response.msg == "好的，我已为您设置明天09:00的闹钟。 提醒事项：吃药。"
    assert response.requires_selection is False


@pytest.mark.asyncio
async def test_user_candidate_resolution(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "HEALTH_MONITOR_GENERAL",
            "result": "健康监测",
            "target": "",
            "confidence": 0.9,
            "reply": "好的，我会为您安排健康监测。",
        },
        {
            "intent_code": "UNKNOWN",
            "confidence": 0.4,
            "reply": "让我确认一下。",
        },
        {
            "match": "小杨",
            "confidence": 0.9,
        },
    ])
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

    first = await service.handle_command(
        CommandRequest(sessionId="sess-user", query="我要健康监测", user="小张,小杨")
    )
    assert first.function_analysis.result == "健康监测"
    assert first.function_analysis.target == ""
    assert first.requires_selection is True

    second = await service.handle_command(
        CommandRequest(sessionId="sess-user", query="晓阳", user="小张,小杨")
    )
    assert second.function_analysis.result == "健康监测"
    assert second.function_analysis.target == "小杨"
    assert second.msg == "好的，我已为小杨打开健康监测功能。"
    assert second.requires_selection is False


@pytest.mark.asyncio
async def test_education_target_refinement(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "EDUCATION_GENERAL",
            "result": "小雅教育",
            "target": "习声乐戏曲",
            "confidence": 0.85,
            "reply": "没问题，我来安排学习课程。",
        }
    ])
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

    response = await service.handle_command(
        CommandRequest(sessionId="sess-edu", query="我想学习声乐戏曲。")
    )

    assert response.function_analysis.result == "小雅教育"
    assert response.function_analysis.target == "声乐戏曲"
    assert "target_calibrated" in (response.function_analysis.reasoning or "")


@pytest.mark.asyncio
async def test_education_target_with_reduplication(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "EDUCATION_GENERAL",
            "result": "小雅教育",
            "target": "",
            "confidence": 0.88,
            "reply": "好的，我会安排学习课程。",
        }
    ])
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

    response = await service.handle_command(
        CommandRequest(sessionId="sess-edu-2", query="我想学学声乐戏曲。")
    )

    assert response.function_analysis.result == "小雅教育"
    assert response.function_analysis.target == "声乐戏曲"
    assert "target_calibrated" in (response.function_analysis.reasoning or "")


@pytest.mark.asyncio
async def test_alarm_target_llm_fallback(monkeypatch):
    fake_llm = SequencedFakeDoubao([
        {
            "intent_code": "ALARM_REMINDER",
            "result": "新增闹钟",
            "target": "",
            "event": None,
            "status": None,
            "confidence": 0.8,
            "reply": "好的",
        },
        {
            "days": 0,
            "hours": 0,
            "minutes": 10,
            "seconds": 0,
            "event": "吃药",
            "confidence": 0.92,
        },
    ])
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

    response = await service.handle_command(
        CommandRequest(sessionId="sess-alarm-llm", query="十分钟之后提醒我吃药")
    )

    assert response.function_analysis.result == "新增闹钟"
    assert response.function_analysis.target
    assert response.function_analysis.event == "吃药"
