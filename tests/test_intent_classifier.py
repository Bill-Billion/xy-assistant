from datetime import datetime

import pytest

from app.services import intent_rules
from app.services.conversation import ConversationState
from app.services.intent_classifier import IntentClassifier
from app.utils.time_utils import EAST_EIGHT


class FakeDoubaoClient:
    def __init__(self, payloads):
        if isinstance(payloads, dict):
            payloads = [payloads]
        self._payloads = list(payloads)

    async def chat(self, system_prompt, messages, response_format=None):  # noqa: D401
        if not self._payloads:
            raise RuntimeError("no more payloads")
        payload = self._payloads.pop(0)
        return (payload.get("raw", ""), payload)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)

    def _fixed_now():
        return base

    monkeypatch.setattr(intent_rules, "now_e8", _fixed_now)
    yield


@pytest.mark.asyncio
async def test_classifier_uses_rule_for_alarm():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "好的，为您设置闹钟。",
            "intent_code": "UNKNOWN",
            "confidence": 0.3,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="abc")
    result = await classifier.classify(
        session_id="abc",
        query="帮我订个6点的闹钟",
        meta={},
        conversation_state=state,
    )
    assert result.function_analysis["result"] == "新增闹钟"
    assert result.function_analysis["target"] == "2024-09-20T18:00:00+08:00"
    assert result.function_analysis["need_clarify"] is False
    assert result.function_analysis["advice"] is None


@pytest.mark.asyncio
async def test_classifier_low_confidence_triggers_clarify():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "我不太确定，您是想听曲艺吗？",
            "intent_code": "UNKNOWN",
            "confidence": 0.2,
            "clarify_message": "您想听戏曲还是看电影呢？",
            "need_clarify": True,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="def")
    result = await classifier.classify(
        session_id="def",
        query="我想娱乐一下",
        meta={},
        conversation_state=state,
    )
    assert result.function_analysis["need_clarify"] is True
    assert result.reply_message


@pytest.mark.asyncio
async def test_classifier_overrides_result_with_allowed_value():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "好的，正在尝试联系小张。",
            "intent_code": "COMMUNICATION_CALL_AUDIO",
            "result": "正在尝试为你联系小张",
            "target": "小张",
            "confidence": 0.9,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="ghi")
    outcome = await classifier.classify(
        session_id="ghi",
        query="我想联系小张",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "小雅音频通话"
    assert outcome.function_analysis["target"] == "小张"
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None


@pytest.mark.asyncio
async def test_classifier_calendar_question_returns_fixed_result():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "我可以帮您查下黄历。",
            "intent_code": "CALENDAR_GENERAL",
            "result": "你可以通过查看黄历等方式来了解明天是否适合搬家",
            "target": "",
            "confidence": 0.82,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="jkl")
    outcome = await classifier.classify(
        session_id="jkl",
        query="明天适合搬家吗",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "日期时间和万年历"
    assert outcome.function_analysis["target"] == ""
    assert outcome.function_analysis.get("advice") is None


@pytest.mark.asyncio
async def test_classifier_unknown_chat_requests_clarification():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "我们可以先聊聊天。",
            "intent_code": "UNKNOWN",
            "confidence": 0.4,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="mno")
    outcome = await classifier.classify(
        session_id="mno",
        query="最近学校怎么样？",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["need_clarify"] is True
    assert outcome.function_analysis["clarify_message"]


@pytest.mark.asyncio
async def test_health_question_provides_advice_and_safety():
    fake_llm = FakeDoubaoClient({
        "reply": "建议您先休息。",
        "intent_code": "UNKNOWN",
        "advice": "建议今天多休息并补充水分。",
        "safety_notice": "小雅的建议仅供参考，如症状持续请及时就医。",
        "confidence": 0.65,
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="health")
    outcome = await classifier.classify(
        session_id="health",
        query="我熬了一晚上头晕怎么办",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "健康科普"
    assert "头晕" in outcome.function_analysis["target"]
    assert outcome.function_analysis["advice"]
    assert outcome.function_analysis["safety_notice"]
    assert outcome.function_analysis["need_clarify"] is False
    assert "就医" in outcome.function_analysis["safety_notice"]


@pytest.mark.asyncio
async def test_classifier_blood_pressure_monitor():
    fake_llm = FakeDoubaoClient({
        "intent_code": "UNKNOWN",
        "confidence": 0.5
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="bp")
    outcome = await classifier.classify(
        session_id="bp",
        query="我需要血压监测",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "血压监测"
    assert outcome.function_analysis["target"] == ""
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None
    assert outcome.function_analysis["safety_notice"] is None


@pytest.mark.asyncio
async def test_doctor_contact_audio():
    fake_llm = FakeDoubaoClient({
        "intent_code": "UNKNOWN",
        "confidence": 0.5
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="doc")
    outcome = await classifier.classify(
        session_id="doc",
        query="请帮我联系下高医生",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "家庭医生音频通话"
    assert "高医生" in outcome.function_analysis["target"]
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None


@pytest.mark.asyncio
async def test_classifier_health_knowledge_query():
    fake_llm = FakeDoubaoClient({
        "intent_code": "UNKNOWN",
        "confidence": 0.4,
        "reply": "头疼可能与多种因素有关，我来为您科普一下。"
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="edu")
    outcome = await classifier.classify(
        session_id="edu",
        query="怎么判断有没有高血压",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["result"] == "健康科普"
    assert outcome.function_analysis["target"] == "判断高血压"
    assert outcome.function_analysis["need_clarify"] is False
