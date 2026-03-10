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

    async def chat(self, system_prompt, messages, response_format=None, overrides=None, timeout=None, max_retries=None):  # noqa: D401
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
async def test_classifier_promotes_entertainment_general_for_toc_query():
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
    assert result.function_analysis["result"] == "娱乐管家"
    assert result.function_analysis["need_clarify"] is False
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
    assert outcome.function_analysis["result"] == ""
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

    assert outcome.function_analysis["result"] == ""
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
    assert outcome.function_analysis["result"] == "家庭医生"
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

    assert outcome.function_analysis["result"] == "家庭医生"
    assert "高医生" in outcome.function_analysis["target"]
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.function_analysis["advice"] is None
    assert "rule_override=FAMILY_DOCTOR_CONTACT<-FAMILY_DOCTOR_GENERAL" in (
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
    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["target"] == "判断高血压"
    assert outcome.function_analysis["need_clarify"] is False
    assert "科普" in outcome.reply_message or "高血压" in outcome.reply_message


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


@pytest.mark.asyncio
async def test_settings_absolute_target_overrides_llm_delta():
    """模型 reply 正确但 target 输出为 +/-10 时，应按“调到/设置为”纠正为绝对值。"""
    fake_llm = FakeDoubaoClient(
        {
            "reply": "已将音量调整至20%。",
            "intent_code": "SETTINGS_SOUND_UP",
            "result": "声音调高",
            "target": "-10",
            "confidence": 0.9,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="settings-abs")
    outcome = await classifier.classify(
        session_id="settings-abs",
        query="把声音调到20%",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["target"] == "20"


@pytest.mark.asyncio
async def test_settings_relative_query_rejects_llm_absolute_target():
    """线上只看 target 执行：相对调节语句不应输出绝对值，避免误当“设置为20”。"""
    fake_llm = FakeDoubaoClient(
        {
            "reply": "好的，已经为您把音量调大一些。",
            "intent_code": "SETTINGS_SOUND_UP",
            "result": "声音调高",
            "target": "20",
            "confidence": 0.9,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="settings-rel")
    outcome = await classifier.classify(
        session_id="settings-rel",
        query="把声音调大一点",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["target"] == "+10"


@pytest.mark.asyncio
async def test_settings_target_sign_aligns_result():
    """target 符号与 result 不一致时，以 target 为准纠正 result，避免结构化字段自相矛盾。"""
    fake_llm = FakeDoubaoClient(
        {
            "reply": "好的，已为您把音量调小一些。",
            "intent_code": "SETTINGS_SOUND_UP",
            "result": "声音调高",
            "target": "-10",
            "confidence": 0.9,
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="settings-sign")
    outcome = await classifier.classify(
        session_id="settings-sign",
        query="把声音调小点",
        meta={},
        conversation_state=state,
    )
    assert outcome.function_analysis["target"] == "-10"
    assert outcome.function_analysis["result"] == "声音调低"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_result", "expected_target"),
    [
        ("我想联系家人", "小雅通话", ""),
        ("我要做服务预约", "小雅预约", ""),
        ("打开二胡学习视频", "小雅教育", "二胡"),
        ("我想看电视", "小雅电影", ""),
        ("我想娱乐一下", "娱乐管家", ""),
        ("取消明天早上8点的闹钟", "取消闹钟", "2024-09-21 08:00:00"),
    ],
)
async def test_classifier_toc_contract_for_general_user_queries(query, expected_result, expected_target):
    fake_llm = FakeDoubaoClient({"intent_code": "UNKNOWN", "confidence": 0.2, "reply": ""})
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id=f"toc-{query}")
    outcome = await classifier.classify(
        session_id=f"toc-{query}",
        query=query,
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == expected_result
    if expected_target:
        assert outcome.function_analysis["target"] == expected_target
    else:
        assert (outcome.function_analysis["target"] or "") == ""
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.reply_message


@pytest.mark.asyncio
async def test_classifier_fills_cancel_alarm_parsed_time_from_rule():
    fake_llm = FakeDoubaoClient({"intent_code": "UNKNOWN", "confidence": 0.2, "reply": ""})
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="alarm-cancel-colon")
    outcome = await classifier.classify(
        session_id="alarm-cancel-colon",
        query="取消下午4:10的闹钟",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "取消闹钟"
    assert outcome.function_analysis["target"] == "2024-09-20 16:10:00"
    assert outcome.function_analysis["parsed_time"] == "2024-09-20 16:10:00"
    assert outcome.function_analysis["time_source"] == "rule"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("给我讲讲高血压相关知识", "高血压相关知识"),
        ("怎么判断有没有高血压", "判断高血压"),
        ("被蜜蜂蛰了怎么办", "处理被蜜蜂蛰了"),
    ],
)
async def test_classifier_health_education_qa_only_broadcasts(query, expected_target):
    fake_llm = FakeDoubaoClient(
        {
            "intent_code": "UNKNOWN",
            "confidence": 0.3,
            "reply": "我来给您说说这个情况。",
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id=f"health-{query}")
    outcome = await classifier.classify(
        session_id=f"health-{query}",
        query=query,
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["target"] == expected_target
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.reply_message


@pytest.mark.asyncio
async def test_classifier_open_health_education_page_keeps_public_result():
    fake_llm = FakeDoubaoClient({"intent_code": "UNKNOWN", "confidence": 0.2, "reply": ""})
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="health-page")
    outcome = await classifier.classify(
        session_id="health-page",
        query="打开健康科普页面",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "健康科普"
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.reply_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_result", "expected_target"),
    [
        ("帮我找王医生看病", "名医问诊", "王医生"),
        ("新增一个用药计划", "用药计划", ""),
        ("新建一个每天吃维生素d的计划", "用药计划", "维生素D"),
        ("帮我联系张三的家庭医生", "家庭医生", "张三"),
        ("帮我给王医生打个电话", "家庭医生", "王医生"),
    ],
)
async def test_classifier_toc_contract_for_medical_and_family_flows(query, expected_result, expected_target):
    fake_llm = FakeDoubaoClient({"intent_code": "UNKNOWN", "confidence": 0.2, "reply": ""})
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id=f"medical-{query}")
    outcome = await classifier.classify(
        session_id=f"medical-{query}",
        query=query,
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == expected_result
    assert (outcome.function_analysis["target"] or "") == expected_target
    assert outcome.function_analysis["need_clarify"] is False
    assert outcome.reply_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "llm_intent", "llm_result", "expected_result", "expected_target"),
    [
        ("打开二胡学习视频", "ENTERTAINMENT_GENERAL", "娱乐管家", "小雅教育", "二胡"),
        ("我想看八段锦", "ENTERTAINMENT_GENERAL", "娱乐管家", "健康科普", "八段锦"),
        ("有点闷，陪我说说话呗。", "JOKE_MODE", "笑话模式", "语音陪伴或聊天", ""),
        ("帮我找王医生看病", "FAMILY_DOCTOR_GENERAL", "家庭医生", "名医问诊", "王医生"),
        ("菜单里是不是有更新选项？帮我找找。", "UNKNOWN", "未知指令", "小雅设置", ""),
        ("帮我瞧瞧老伴最近身体数据怎么样。", "HEALTH_MONITOR_GENERAL", "健康监测", "健康画像", "老伴"),
        ("现在多少度", "TIME_BROADCAST", "播报时间", "今天天气", "今天"),
        ("想看看商城里有没有温度计。", "MALL_GENERAL", "商城", "健康监测终端", ""),
        ("阳台窗户合不上，能不能安排个人来修修。", "HOME_SERVICE_GENERAL", "小雅预约", "房屋维修", ""),
        ("我想看电影", "ENTERTAINMENT_GENERAL", "娱乐管家", "小雅电影", ""),
    ],
)
async def test_classifier_promotes_rule_candidate_for_toc_edge_cases(
    query,
    llm_intent,
    llm_result,
    expected_result,
    expected_target,
):
    fake_llm = FakeDoubaoClient(
        {
            "reply": "我先帮您处理。",
            "intent_candidates": [
                {
                    "intent_code": llm_intent,
                    "result": llm_result,
                    "target": "",
                    "confidence": 0.92,
                    "reason": "llm guess",
                }
            ],
            "weather_info": {
                "location": {"name": "", "type": "", "confidence": 0},
                "datetime": {"text": "", "iso": "", "confidence": 0},
                "needs_realtime_data": False,
                "weather_summary": "",
                "weather_condition": "",
                "weather_confidence": 0,
            },
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id=f"promote-{query}")
    outcome = await classifier.classify(
        session_id=f"promote-{query}",
        query=query,
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == expected_result
    assert (outcome.function_analysis["target"] or "") == expected_target
    assert outcome.function_analysis["need_clarify"] is False


@pytest.mark.asyncio
async def test_classifier_keeps_health_education_result_for_content_browse_query():
    fake_llm = FakeDoubaoClient(
        {
            "intent_candidates": [
                {
                    "intent_code": "ENTERTAINMENT_GENERAL",
                    "result": "娱乐管家",
                    "target": "",
                    "confidence": 0.9,
                }
            ],
            "reply": "",
        }
    )
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="health-content")
    outcome = await classifier.classify(
        session_id="health-content",
        query="我想看八段锦",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == "健康科普"
    assert outcome.function_analysis["target"] == "八段锦"
    assert outcome.function_analysis["need_clarify"] is False


@pytest.mark.asyncio
async def test_classifier_unknown_uses_natural_local_clarify_message():
    fake_llm = FakeDoubaoClient({
        "reply": "",
        "intent_code": "UNKNOWN",
        "confidence": 0.2,
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="local-clarify")
    outcome = await classifier.classify(
        session_id="local-clarify",
        query="最近学校怎么样？",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["need_clarify"] is True
    assert "再多说一点" in outcome.function_analysis["clarify_message"]
    assert "下一步怎么处理" in outcome.function_analysis["clarify_message"]
    assert "直接回答问题" not in outcome.function_analysis["clarify_message"]
    assert "打开小雅功能" not in outcome.function_analysis["clarify_message"]


@pytest.mark.asyncio
async def test_classifier_vague_symptom_local_clarify_is_contextual():
    fake_llm = FakeDoubaoClient({
        "reply": "",
        "intent_code": "UNKNOWN",
        "confidence": 0.2,
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="vague-symptom-clarify")
    outcome = await classifier.classify(
        session_id="vague-symptom-clarify",
        query="我感觉好热",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["need_clarify"] is True
    clarify = outcome.function_analysis["clarify_message"] or ""
    assert "闷热" in clarify
    assert "发热" in clarify
    assert "查天气" in clarify
    assert "记录体温" in clarify
    assert "直接回答问题" not in clarify
    assert "打开小雅功能" not in clarify


@pytest.mark.asyncio
async def test_classifier_prefers_llm_reply_as_clarify_message():
    expected_reply = "您是觉得室内闷热，还是身体有发热感呢？如果需要，我也可以帮您查天气。"
    fake_llm = FakeDoubaoClient({
        "reply": expected_reply,
        "intent_code": "UNKNOWN",
        "confidence": 0.2,
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(session_id="llm-reply-clarify")
    outcome = await classifier.classify(
        session_id="llm-reply-clarify",
        query="我感觉好热",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["need_clarify"] is True
    assert outcome.function_analysis["clarify_message"] == expected_reply
    reasoning = outcome.function_analysis["reasoning"] or ""
    assert "llm_reply_as_clarify" in reasoning
    assert "local_clarify_fallback" not in reasoning


@pytest.mark.asyncio
async def test_classifier_unknown_uses_numbered_choices_on_third_clarify_round():
    fake_llm = FakeDoubaoClient({
        "reply": "",
        "intent_code": "UNKNOWN",
        "confidence": 0.2,
    })
    classifier = IntentClassifier(fake_llm, confidence_threshold=0.7)
    state = ConversationState(
        session_id="local-clarify-round3",
        pending_clarification=True,
        clarify_message="上轮没有听清",
        clarify_rounds=2,
    )
    outcome = await classifier.classify(
        session_id="local-clarify-round3",
        query="还是这个意思",
        meta={},
        conversation_state=state,
    )

    assert outcome.function_analysis["result"] == ""
    assert outcome.function_analysis["need_clarify"] is True
    assert "回复1" in outcome.function_analysis["clarify_message"]
    assert "回复2" in outcome.function_analysis["clarify_message"]
