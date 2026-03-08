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
    monkeypatch.setattr("app.utils.time_utils.now_e8", _fixed_now)
    yield


@pytest.mark.asyncio
async def test_classifier_uses_rule_for_alarm():
    fake_llm = FakeDoubaoClient(
        {
            "reply": "好的，我已为您设置今天18:00的闹钟。",
            "intent_candidates": [
                {
                    "intent_code": "ALARM_CREATE",
                    "result": "新增闹钟",
                    "target": "2024-09-20 18:00:00",
                    "parsed_time": "2024-09-20 18:00:00",
                    "time_text": "今天下午6点",
                    "time_confidence": 0.9,
                    "event": "晚间提醒",
                    "event_confidence": 0.9,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.95,
                    "reason": "解析出 18:00 并提炼事件",
                }
            ],
            "weather_info": {"location": {"name": "", "type": "", "confidence": 0}, "datetime": {"text": "", "iso": "", "confidence": 0}, "needs_realtime_data": False, "weather_summary": "", "weather_condition": "", "weather_confidence": 0},
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
    assert result.function_analysis["target"] == "2024-09-20 18:00:00"
    assert result.function_analysis["parsed_time"] == "2024-09-20 18:00:00"
    assert result.function_analysis["time_source"] == "llm"
    assert result.function_analysis["need_clarify"] is False
    assert result.function_analysis["advice"] is None
    assert result.reply_message == "好的，我已为您设置今天18:00的闹钟。"


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
    assert outcome.reply_message == "好的，正在尝试联系小张。"


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
    assert outcome.reply_message == "我可以帮您查下黄历。"


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
    assert outcome.reply_message == "建议您先休息。"


@pytest.mark.asyncio
async def test_classifier_prefers_llm_candidates_over_rules():
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "HEALTH_EDUCATION",
                    "result": "健康科普",
                    "target": "高血压日常饮食",
                    "parsed_time": "",
                    "event": "",
                    "event_confidence": 0.0,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.82,
                    "reason": "询问饮食建议，属于健康知识类",
                    "reply_hint": "科普饮食建议",
                },
                {
                    "intent_code": "HEALTH_MONITOR_BLOOD_PRESSURE",
                    "result": "血压监测",
                    "target": "",
                    "parsed_time": "",
                    "event": "",
                    "event_confidence": 0.0,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.2,
                    "reason": "包含血压关键词但未表达监测需求",
                },
            ],
            "reply": "高血压患者日常饮食应注意低盐低脂，多吃新鲜蔬果……",
            "advice": "高血压患者日常饮食应遵循低盐低脂原则。",
            "safety_notice": "小雅的建议仅供参考，如血压异常请及时咨询医生。",
            "need_clarify": False,
        }
    )

    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="edu")
    outcome = await classifier.classify(
        session_id="edu",
        query="我想了解下高血压日常吃什么",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "健康科普"
    assert outcome.function_analysis["target"] == "高血压日常饮食"
    assert outcome.function_analysis["need_clarify"] is False
    assert "医生" in outcome.function_analysis["safety_notice"]
    assert outcome.reply_message.startswith("高血压患者日常饮食应注意")


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
async def test_classifier_promotes_rule_specific_monitor_when_llm_generic():
    fake_llm = FakeDoubaoClient({
        "intent_candidates": [
            {
                "intent_code": "HEALTH_MONITOR_GENERAL",
                "result": "健康监测",
                "target": "",
                "parsed_time": "",
                "event": "",
                "event_confidence": 0.0,
                "status": "",
                "status_confidence": 0.0,
                "confidence": 1.0,
                "reason": "模型给出泛化健康监测意图",
            }
        ],
        "need_clarify": True,
        "clarify_message": "您是想了解监测方法还是其他健康需求呢？",
        "advice": "建议保持健康生活方式。",
        "safety_notice": "健康建议仅供参考。",
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="bp-override")
    outcome = await classifier.classify(
        session_id="bp-override",
        query="我需要血压监测",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "血压监测"
    assert outcome.function_analysis["target"] == ""
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None
    assert outcome.function_analysis["safety_notice"] is None
    assert "rule_override=HEALTH_MONITOR_BLOOD_PRESSURE<-HEALTH_MONITOR_GENERAL" in (
        outcome.function_analysis["reasoning"] or ""
    )


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
async def test_classifier_promotes_rule_for_doctor_contact():
    fake_llm = FakeDoubaoClient({
        "intent_candidates": [
            {
                "intent_code": "FAMILY_DOCTOR_GENERAL",
                "result": "家庭医生",
                "target": "",
                "parsed_time": "",
                "event": "",
                "event_confidence": 0.0,
                "status": "",
                "status_confidence": 0.0,
                "confidence": 0.92,
                "reason": "模型识别为泛化家庭医生功能",
            }
        ],
        "need_clarify": True,
        "clarify_message": "您是想联系哪位家庭医生呢？",
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="doctor-override")
    outcome = await classifier.classify(
        session_id="doctor-override",
        query="请帮我联系下高医生",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "家庭医生音频通话"
    assert "高医生" in outcome.function_analysis["target"]
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None
    assert "rule_override=FAMILY_DOCTOR_CALL_AUDIO<-FAMILY_DOCTOR_GENERAL" in (
        outcome.function_analysis["reasoning"] or ""
    )


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


@pytest.mark.asyncio
async def test_classifier_reply_fallback_when_missing():
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "ALARM_CREATE",
                    "result": "新增闹钟",
                    "target": "2024-09-21 09:00:00",
                    "parsed_time": "2024-09-21 09:00:00",
                    "time_text": "明早9点",
                    "time_confidence": 0.88,
                    "event": "提醒喝水",
                    "event_confidence": 0.82,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.88,
                    "reason": "解析出明早9点的闹钟并识别提醒事项",
                }
            ],
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="alarm-fallback")
    outcome = await classifier.classify(
        session_id="alarm-fallback",
        query="定个明早9点的闹钟",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "新增闹钟"
    assert outcome.function_analysis["event"] == "喝水"
    assert outcome.function_analysis["parsed_time"] == "2024-09-21 09:00:00"
    assert outcome.function_analysis["time_confidence"] == 0.88
    assert outcome.reply_message  # fallback 给出的消息不应为空
    assert "提醒您喝水" in outcome.reply_message


@pytest.mark.asyncio
async def test_reasoning_deduplicated():
    repeated_text = "闹钟请求，规则命中"
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "ALARM_CREATE",
                    "result": "新增闹钟",
                    "confidence": 0.9,
                    "reason": repeated_text,
                }
            ],
            "reasoning": repeated_text,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="dedup")
    outcome = await classifier.classify(
        session_id="dedup",
        query="帮我订个6点的闹钟",
        meta={},
        conversation_state=state,
    )

    reasoning = outcome.function_analysis.get("reasoning") or ""
    assert reasoning.count(repeated_text) == 1


@pytest.mark.asyncio
async def test_alarm_low_time_confidence_requires_clarify():
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "ALARM_CREATE",
                    "result": "新增闹钟",
                    "target": "2024-09-21 09:00:00",
                    "parsed_time": "2024-09-21 09:00:00",
                    "time_text": "明早9点",
                    "time_confidence": 0.3,
                    "event": "晨练",
                    "event_confidence": 0.8,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.85,
                    "reason": "识别到闹钟请求，但时间置信度较低",
                }
            ],
            "reply": "",
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="alarm-low-conf")
    outcome = await classifier.classify(
        session_id="alarm-low-conf",
        query="帮我定个明早九点的闹钟提醒我晨练",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["need_clarify"] is True
    assert outcome.function_analysis["clarify_message"]
    assert outcome.function_analysis["time_confidence"] == 0.3


@pytest.mark.asyncio
async def test_alarm_event_from_llm_override_rule():
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "ALARM_CREATE",
                    "result": "新增闹钟",
                    "target": "2024-11-26 09:00:00",
                    "parsed_time": "2024-11-26 09:00:00",
                    "time_text": "十一月二十六日上午九点",
                    "time_confidence": 0.9,
                    "event": "提醒妈妈生日",
                    "event_confidence": 0.92,
                    "status": "",
                    "status_confidence": 0.0,
                    "confidence": 0.9,
                    "reason": "识别为闹钟设置并提取提醒事项",
                }
            ],
            "reply": "好的，我已经为您设置闹钟。",
        }
    )

    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="alarm-event")
    outcome = await classifier.classify(
        session_id="alarm-event",
        query="定个十一月二十六的闹钟提醒我妈妈生日",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "新增闹钟"
    assert outcome.function_analysis["event"] == "妈妈生日"
    assert outcome.function_analysis["parsed_time"] == "2024-11-26 09:00:00"
    reasoning = outcome.function_analysis["reasoning"] or ""
    assert "alarm_details=llm" in reasoning
