from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from time import perf_counter
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.conversation import ConversationState
from app.services.intent_definitions import INTENT_DEFINITIONS, IntentCode
from app.services.intent_rules import RuleResult, extract_settings_absolute_value, extract_settings_relative_delta, run_rules
from app.services.llm_client import DoubaoClient
from app.services.target_refiner import TargetRefiner
from app.services.prompt_templates import build_system_prompt, get_allowed_results
from app.utils.time_utils import EAST_EIGHT, now_e8, sanitize_person_name
from app.core.config import get_settings



HEALTH_KEYWORDS = {
    "头晕", "头痛", "血压", "血糖", "血脂", "熬夜", "失眠",
    "感冒", "发烧", "咳嗽", "疼", "不舒服", "痛", "疲劳",
    "药", "治疗", "心脏", "胃", "骨折", "康复", "健康",
}
DEFAULT_SAFETY_NOTICE = (
    "小雅的建议仅供参考，不替代专业医疗意见，如症状持续或加重请及时咨询医生。"
)

WEATHER_INTENT_CODES = {
    IntentCode.WEATHER_TODAY,
    IntentCode.WEATHER_TOMORROW,
    IntentCode.WEATHER_DAY_AFTER,
    IntentCode.WEATHER_SPECIFIC,
    IntentCode.WEATHER_OUT_OF_RANGE,
}

SETTINGS_RESULTS = {"声音调高", "声音调低", "亮度调高", "亮度调低"}
SETTINGS_UP_RESULTS = {"声音调高", "亮度调高"}
SETTINGS_DOWN_RESULTS = {"声音调低", "亮度调低"}

# 可直接执行的健康类意图（无需进一步澄清即可跳转前端功能）。
ACTIONABLE_HEALTH_INTENTS = {
    IntentCode.HEALTH_MONITOR_GENERAL,
    IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE,
    IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN,
    IntentCode.HEALTH_MONITOR_HEART_RATE,
    IntentCode.HEALTH_MONITOR_BLOOD_SUGAR,
    IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS,
    IntentCode.HEALTH_MONITOR_WEIGHT,
    IntentCode.HEALTH_MONITOR_BODY_TEMPERATURE,
    IntentCode.HEALTH_MONITOR_HEMOGLOBIN,
    IntentCode.HEALTH_MONITOR_URIC_ACID,
    IntentCode.HEALTH_MONITOR_SLEEP,
    IntentCode.HEALTH_PROFILE,
    IntentCode.HEALTH_EVALUATION,
}

# 可直接执行的医生联系类意图。
ACTIONABLE_CONTACT_INTENTS = {
    IntentCode.FAMILY_DOCTOR_GENERAL,
    IntentCode.FAMILY_DOCTOR_CONTACT,
    IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
    IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
    IntentCode.HEALTH_DOCTOR_GENERAL,
    IntentCode.HEALTH_DOCTOR_SPECIFIC,
}

# 所有可立即落地的意图合集。
ACTIONABLE_INTENTS = ACTIONABLE_HEALTH_INTENTS | ACTIONABLE_CONTACT_INTENTS | {
    *WEATHER_INTENT_CODES,
    IntentCode.ALARM_CREATE,
    IntentCode.ALARM_REMINDER,
    IntentCode.ALARM_CANCEL,
    IntentCode.ALARM_VIEW,
    IntentCode.CALENDAR_GENERAL,
    IntentCode.SETTINGS_GENERAL,
    IntentCode.MEDICATION_REMINDER_VIEW,
    IntentCode.MEDICATION_REMINDER_CREATE,
    IntentCode.HEALTH_SPECIALIST,
    IntentCode.CHAT,
    IntentCode.COMMUNICATION_GENERAL,
    IntentCode.COMMUNICATION_CALL_AUDIO,
    IntentCode.COMMUNICATION_CALL_VIDEO,
    IntentCode.ENTERTAINMENT_MUSIC,
    IntentCode.ENTERTAINMENT_OPERA,
    IntentCode.ENTERTAINMENT_AUDIOBOOK,
    IntentCode.ENTERTAINMENT_MUSIC_OFF,
    IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF,
    IntentCode.ENTERTAINMENT_OPERA_OFF,
    IntentCode.ENTERTAINMENT_RESUME,
    IntentCode.JOKE_MODE,
    IntentCode.ENTERTAINMENT_GENERAL,
    IntentCode.ENTERTAINMENT_MOVIE,
    IntentCode.HOME_SERVICE_GENERAL,
    IntentCode.HOME_SERVICE_APPLIANCE,
    IntentCode.HOME_SERVICE_HOUSE,
    IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    IntentCode.HOME_SERVICE_MATERNAL,
    IntentCode.HOME_SERVICE_DOMESTIC,
    IntentCode.HOME_SERVICE_FOOT,
    IntentCode.EDUCATION_GENERAL,
    IntentCode.MALL_GENERAL,
    IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
    IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    IntentCode.MALL_SMART_LIFE_TERMINAL,
    IntentCode.MALL_HEALTH_FOOD,
    IntentCode.MALL_SILVER_PRODUCTS,
    IntentCode.MALL_DAILY_PRODUCTS,
    IntentCode.MALL_ORDERS,
    IntentCode.ALBUM,
    IntentCode.DEVICE_SCREEN_OFF,
    IntentCode.SETTINGS_SOUND_UP,
    IntentCode.SETTINGS_SOUND_DOWN,
    IntentCode.SETTINGS_BRIGHTNESS_UP,
    IntentCode.SETTINGS_BRIGHTNESS_DOWN,
}

# 规则兜底/提升白名单：仅允许这些“高确定性、强可执行”的意图被规则纠偏/补全，
# 避免“娱乐一下/来点什么”等含糊表达被模板短路，保持大模型澄清能力。
SAFE_RULE_MERGE_INTENTS = (
    ACTIONABLE_INTENTS
    | {
        IntentCode.HEALTH_EDUCATION,
        IntentCode.TIME_BROADCAST,
    }
)

# LLM 事件解析参数
EVENT_CONFIDENCE_THRESHOLD = 0.6
EVENT_MIN_LENGTH = 2
TIME_CONFIDENCE_THRESHOLD = 0.6
EVENT_TIME_TOKENS = {
    "今天",
    "明天",
    "后天",
    "今早",
    "明早",
    "后早",
    "上午",
    "下午",
    "晚上",
    "早上",
    "凌晨",
    "傍晚",
    "中午",
    "夜里",
    "当前",
}
EVENT_PREFIX_TOKENS = {
    "提醒",
    "帮我提醒",
    "请提醒",
    "帮我记得",
    "让我记得",
    "要记得",
    "麻烦提醒",
    "帮我",
    "定个",
    "定",
    "订个",
    "订",
    "设定",
    "设置",
}

# 规则优先映射：当大模型仅识别出泛化意图时，用于提升规则识别的细分意图。
INTENT_OVERRIDE_MAP: dict[IntentCode, set[IntentCode]] = {
    IntentCode.HEALTH_MONITOR_GENERAL: (ACTIONABLE_HEALTH_INTENTS - {IntentCode.HEALTH_MONITOR_GENERAL}) | {IntentCode.HEALTH_EDUCATION},
    IntentCode.HEALTH_EVALUATION: {IntentCode.HEALTH_PROFILE},
    IntentCode.FAMILY_DOCTOR_GENERAL: {
        IntentCode.FAMILY_DOCTOR_CONTACT,
        IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
        IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
        IntentCode.HEALTH_SPECIALIST,
    },
    IntentCode.FAMILY_DOCTOR_CONTACT: {
        IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
        IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
        IntentCode.HEALTH_SPECIALIST,
    },
    IntentCode.FAMILY_DOCTOR_CALL_AUDIO: {
        IntentCode.HEALTH_SPECIALIST,
    },
    IntentCode.FAMILY_DOCTOR_CALL_VIDEO: {
        IntentCode.HEALTH_SPECIALIST,
    },
    IntentCode.COMMUNICATION_CALL_AUDIO: {
        IntentCode.FAMILY_DOCTOR_GENERAL,
        IntentCode.FAMILY_DOCTOR_CONTACT,
        IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
    },
    IntentCode.COMMUNICATION_CALL_VIDEO: {
        IntentCode.FAMILY_DOCTOR_GENERAL,
        IntentCode.FAMILY_DOCTOR_CONTACT,
        IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
        IntentCode.EDUCATION_GENERAL,
    },
    IntentCode.COMMUNICATION_GENERAL: {
        IntentCode.COMMUNICATION_CALL_AUDIO,
        IntentCode.COMMUNICATION_CALL_VIDEO,
    },
    IntentCode.ENTERTAINMENT_GENERAL: {
        IntentCode.ENTERTAINMENT_MOVIE,
        IntentCode.ENTERTAINMENT_OPERA,
        IntentCode.ENTERTAINMENT_OPERA_SPECIFIC,
        IntentCode.ENTERTAINMENT_MUSIC,
        IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC,
        IntentCode.ENTERTAINMENT_AUDIOBOOK,
        IntentCode.GAME_DOU_DI_ZHU,
        IntentCode.GAME_CHINESE_CHESS,
        IntentCode.CHAT,
        IntentCode.EDUCATION_GENERAL,
        IntentCode.HEALTH_EDUCATION,
    },
    IntentCode.ENTERTAINMENT_OPERA: {IntentCode.ENTERTAINMENT_OPERA_SPECIFIC},
    IntentCode.ENTERTAINMENT_MUSIC: {IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC},
    IntentCode.JOKE_MODE: {IntentCode.CHAT},
    IntentCode.HOME_SERVICE_GENERAL: {
        IntentCode.HOME_SERVICE_APPLIANCE,
        IntentCode.HOME_SERVICE_HOUSE,
        IntentCode.HOME_SERVICE_WATER_ELECTRIC,
        IntentCode.HOME_SERVICE_MATERNAL,
        IntentCode.HOME_SERVICE_DOMESTIC,
        IntentCode.HOME_SERVICE_FOOT,
    },
    IntentCode.MALL_GENERAL: {
        IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
        IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
        IntentCode.MALL_SMART_LIFE_TERMINAL,
        IntentCode.MALL_HEALTH_FOOD,
        IntentCode.MALL_SILVER_PRODUCTS,
        IntentCode.MALL_DAILY_PRODUCTS,
        IntentCode.MALL_ORDERS,
    },
    IntentCode.HEALTH_DOCTOR_GENERAL: {IntentCode.HEALTH_DOCTOR_SPECIFIC},
    IntentCode.TIME_BROADCAST: set(WEATHER_INTENT_CODES),
    IntentCode.MEDICATION_REMINDER_VIEW: ACTIONABLE_HEALTH_INTENTS,
    IntentCode.MEDICATION_REMINDER_CREATE: ACTIONABLE_HEALTH_INTENTS,
    IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE: {IntentCode.HEALTH_EDUCATION},
    IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN: {IntentCode.HEALTH_EDUCATION},
    IntentCode.HEALTH_MONITOR_HEART_RATE: {IntentCode.HEALTH_EDUCATION},
    IntentCode.HEALTH_MONITOR_BLOOD_SUGAR: {IntentCode.HEALTH_EDUCATION},
    IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS: {IntentCode.HEALTH_EDUCATION},
}

# 允许规则覆盖大模型结果的置信度容差，避免置信度接近时保留泛化意图。
RULE_PROMOTION_TOLERANCE = 0.1

RESULTS_REQUIRING_USER = {
    "健康监测",
    "血压监测",
    "血氧监测",
    "心率监测",
    "血糖监测",
    "血脂监测",
    "体重监测",
    "体温监测",
    "血红蛋白监测",
    "尿酸监测",
    "睡眠监测",
    "健康评估",
    "健康画像",
    "家庭医生",
}

CHAT_KEYWORDS = {
    "聊天",
    "聊聊",
    "聊会儿",
    "聊一会",
    "陪我聊",
    "陪我聊聊",
    "陪我说说话",
    "说说话",
    "唠嗑",
    "唠会儿",
}

# 社交性短语：直接回复，不触发功能也不澄清
# 注意：不包含"好/好的/行/可以/嗯/嗯嗯/明白/知道了"等确认词，
# 这些词在多轮澄清中常作为肯定回复，放入此处会中断澄清流程。
# 同理不包含"小雅"（唤醒词，用户可能还要继续说指令）。
SOCIAL_GREETING_PATTERNS = {
    "你好", "您好", "早上好", "下午好", "晚上好", "早安", "晚安",
    "谢谢", "谢谢你", "谢谢啦", "多谢", "感谢",
    "再见", "拜拜", "回见",
    "辛苦了", "麻烦你了",
    "小雅你好", "在吗", "你在吗",
}


def _is_social_greeting(query: str) -> bool:
    q = (query or "").strip().rstrip("。！？!?~～，,")
    return q in SOCIAL_GREETING_PATTERNS


@dataclass
class ClassificationResult:
    """Container returned by the classifier and consumed by the API layer."""

    reply_message: str
    function_analysis: Dict[str, Any]
    raw_llm_output: str


class IntentClassifier:
    """混合意图分类器：结合规则引擎与大模型推理产出结构化命令。"""

    def __init__(self, llm_client: DoubaoClient, confidence_threshold: float) -> None:
        """初始化依赖并生成系统提示词。"""
        self._llm_client = llm_client
        self._confidence_threshold = confidence_threshold
        settings = get_settings()
        self._system_prompt = build_system_prompt()
        self._allowed_results = get_allowed_results()
        self._target_refiner = TargetRefiner(llm_client)
        self._default_city = settings.weather_default_city

    async def classify(
        self,
        session_id: str,
        query: str,
        meta: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> ClassificationResult:
        """对用户输入进行分类，生成结构化分析结果与回复。"""
        # 默认由大模型完成意图与指令识别；规则仅作为“模型不可用/无输出”时的兜底。
        rule_result: Optional[RuleResult] = None

        llm_response_text = ""
        llm_parsed: dict[str, Any] = {}
        llm_reply: str = ""
        try:
            # 汇总对话历史，保证模型理解当前上下文。
            messages = conversation_state.as_messages()
            reference_message = self._build_reference_message(query, None, meta, conversation_state)
            if reference_message:
                messages.append({"role": "assistant", "content": reference_message})
            messages.append({"role": "user", "content": query})
            classify_llm_start = perf_counter()
            llm_response_text, llm_parsed = await self._llm_client.chat(
                system_prompt=self._system_prompt,
                messages=messages,
                overrides={"thinking": {"type": "disabled"}},
            )
            if isinstance(llm_parsed, dict):
                llm_reply = (llm_parsed.get("reply") or "").strip()
            logger.debug(
                "timing intent_classifier",
                step="primary_llm",
                duration=round(perf_counter() - classify_llm_start, 3),
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM 调用失败，采用规则兜底", error=str(exc))

        candidate_rule_result = run_rules(query, meta)
        llm_has_output = isinstance(llm_parsed, dict) and bool(llm_parsed)
        # 若大模型无任何结构化输出（例如离线/被禁用/返回空对象），使用规则作为兜底。
        if not llm_has_output:
            rule_result = candidate_rule_result
            logger.debug(
                "rule_result_fallback",
                session_id=session_id,
                rule_intent=getattr(rule_result, "intent_code", None),
                rule_target=getattr(rule_result, "target", None),
            )
        # 大模型有输出时：仅对“高确定性白名单意图”引入规则结果用于纠偏/补全
        elif (
            candidate_rule_result is not None
            and candidate_rule_result.intent_code in SAFE_RULE_MERGE_INTENTS
        ):
            rule_result = candidate_rule_result
            logger.debug(
                "rule_result_merge",
                session_id=session_id,
                rule_intent=getattr(rule_result, "intent_code", None),
                rule_target=getattr(rule_result, "target", None),
            )

        function_analysis, intent_code, merge_meta = self._merge_results(rule_result, llm_parsed, query)
        # 对“音量/亮度”类指令，线上仅看 target 执行；因此需要对 target 做强约束纠偏，
        # 避免模型 reply 正确但结构化字段不符合规则导致误执行。
        self._coerce_settings_target(
            query=query,
            function_analysis=function_analysis,
            candidate_rule_result=candidate_rule_result,
        )
        await self._resolve_user_target(
            query=query,
            function_analysis=function_analysis,
            conversation_state=conversation_state,
            meta=meta,
        )
        await self._refine_content_target(
            intent_code=intent_code,
            query=query,
            function_analysis=function_analysis,
        )
        self._apply_toc_contract(
            query=query,
            intent_code=intent_code,
            function_analysis=function_analysis,
        )
        reply_message = llm_reply or ""
        if not function_analysis.get("need_clarify") and (
            llm_parsed.get("need_clarify") or llm_parsed.get("clarify_message")
        ):
            reply_message = ""

        if self._should_clarify(function_analysis):
            function_analysis["need_clarify"] = True
            clarify_message = (function_analysis.get("clarify_message") or "").strip()
            if not clarify_message or clarify_message == "我还不太确定您的意思，您可以再具体说说想做什么吗？":
                clarify_message = self._build_local_clarify_message(
                    query=query,
                    function_analysis=function_analysis,
                    conversation_state=conversation_state,
                    candidate_rule_result=candidate_rule_result,
                )
                function_analysis["clarify_message"] = clarify_message
                self._append_reasoning_marker(function_analysis, "local_clarify_fallback")
            reply_message = clarify_message or reply_message
        else:
            function_analysis.setdefault("need_clarify", False)
            if not reply_message:
                reply_message = self._default_reply(function_analysis)

        # 多轮澄清：若上一轮 result 为空且仍处于澄清中，保持 result 为空，避免回退为“未知指令”干扰前端路由
        if function_analysis.get("need_clarify"):
            last_fa = conversation_state.last_function_analysis or {}
            last_result = (last_fa.get("result") or "").strip()
            if last_result == "":
                current_result = (function_analysis.get("result") or "").strip()
                if current_result in {"未知指令"}:
                    function_analysis["result"] = ""

        logger.info(
            "classification completed",
            session_id=session_id,
            function_analysis=function_analysis,
            llm_parsed=llm_parsed,
            reply_source="llm" if llm_reply else "fallback",
            merge_meta=merge_meta,
        )

        return ClassificationResult(
            reply_message=reply_message,
            function_analysis=function_analysis,
            raw_llm_output=llm_response_text or json.dumps(llm_parsed, ensure_ascii=False),
        )

    def _build_reference_message(
        self,
        query: str,
        rule_result: Optional[RuleResult],
        meta: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> Optional[str]:
        """将规则提示、时间等参考信息打包成辅助消息提供给大模型。"""
        def _needs_weather_context(q: str) -> bool:
            q = (q or "").strip()
            if not q:
                return False
            tokens = [
                "天气",
                "下雨",
                "带伞",
                "雨具",
                "降雨",
                "降温",
                "气温",
                "温度",
                "几度",
                "多少度",
                "℃",
                "湿度",
                "风力",
                "刮风",
                "穿什么",
                "要不要穿",
                "热",
                "冷",
                "闷",
                "潮",
                "晒",
                "体温",
                "发烧",
                "发热",
            ]
            return any(tok in q for tok in tokens)

        def _needs_time_context(q: str) -> bool:
            q = (q or "").strip()
            if not q:
                return False
            tokens = [
                "今天",
                "明天",
                "后天",
                "下周",
                "周",
                "星期",
                "几号",
                "日期",
                "农历",
                "闹钟",
                "提醒",
                "几点",
                "时间",
                "早上",
                "下午",
                "晚上",
                "凌晨",
            ]
            return any(tok in q for tok in tokens)

        need_weather = _needs_weather_context(query) or (
            rule_result is not None and getattr(rule_result, "intent_code", None) in WEATHER_INTENT_CODES
        )
        need_time = _needs_time_context(query)

        hints: list[str] = []
        hints.append("参考信息（仅供参考，请以实际语义为准）")
        # 多轮澄清：提供当前轮次，帮助模型在 3 轮内逐步收敛
        if conversation_state and getattr(conversation_state, "pending_clarification", False):
            rounds = getattr(conversation_state, "clarify_rounds", 0) or 0
            hints.append(f"- 澄清轮次：{min(rounds, 3)}/3")
            last_tip = getattr(conversation_state, "clarify_message", None)
            if isinstance(last_tip, str) and last_tip.strip():
                hints.append(f"- 上轮澄清提示：{last_tip.strip()}")
            # 注入上一轮意图分析，帮助 LLM 延续多轮上下文
            last_fa = getattr(conversation_state, "last_function_analysis", None)
            if isinstance(last_fa, dict) and conversation_state.pending_clarification:
                last_result = (last_fa.get("result") or "").strip()
                last_target = (last_fa.get("target") or "").strip()
                last_event = (last_fa.get("event") or "").strip()
                if last_result:
                    hints.append(f"- 上轮识别功能：{last_result}")
                if last_target:
                    hints.append(f"- 上轮 target：{last_target}")
                if last_event:
                    hints.append(f"- 上轮事件：{last_event}")
                # 告知 LLM 缺失什么信息
                if last_result in {"新增闹钟", "新增提醒"} and not last_target:
                    hints.append("- 上轮待补充：具体时间")
                elif last_result and not last_target:
                    hints.append("- 上轮待补充：目标对象")
                hints.append("- 若用户在补充缺失信息，请继续使用上轮意图，仅补全缺失部分。")
        base_time = now_e8()
        weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        if need_time or need_weather:
            hints.append(
                f"- 当前时间（东八区）：{base_time.strftime('%Y-%m-%d %H:%M')}（{weekday_labels[base_time.weekday()]}）"
            )
        if need_weather:
            hints.append(f"- 默认城市：{self._default_city}（若用户未说明地点，请使用此城市）")
        if need_time or need_weather:
            future_7 = []
            future_14 = []
            for offset in range(1, 15):
                future_day = base_time + timedelta(days=offset)
                fragment = f"{future_day.strftime('%m-%d')}({weekday_labels[future_day.weekday()]})"
                if offset <= 7:
                    future_7.append(fragment)
                else:
                    future_14.append(fragment)
            if future_7:
                hints.append(f"- 未来7天：{', '.join(future_7)}")
            if future_14:
                hints.append(f"- 8-14天：{', '.join(future_14)}")
        if rule_result:
            hints.append(f"- 规则候选功能：{rule_result.intent_code.value}")
            if rule_result.result:
                hints.append(f"- 候选 result：{rule_result.result}")
            if rule_result.target:
                hints.append(f"- 候选 target：{rule_result.target}")
            if getattr(rule_result, "weather_condition", None):
                hints.append(f"- 关注天气要素：{rule_result.weather_condition}")
        user_candidates = meta.get("user_candidates") if meta else None
        if isinstance(user_candidates, str):
            user_list = [item.strip() for item in user_candidates.split(",") if item.strip()]
        elif isinstance(user_candidates, list):
            user_list = [str(item).strip() for item in user_candidates if str(item).strip()]
        else:
            user_list = []
        if user_list:
            hints.append(f"- 当前候选用户：{', '.join(user_list)}")
        context_meta = meta.get("context") if isinstance(meta, dict) else None
        if need_weather and isinstance(context_meta, dict):
            local_weather = context_meta.get("local_weather")
            if isinstance(local_weather, dict):
                city = local_weather.get("city") or self._default_city
                summary = local_weather.get("summary_short") or local_weather.get("summary")
                if summary:
                    hints.append(f"- 本地天气：{city} {summary}")
        # 上下文信息可能包含 local_weather 等噪声，非必要不注入，避免模型“顺手聊天气”
        if meta and (need_time or need_weather or user_list):
            hints.append(f"- 上下文信息：{json.dumps(meta, ensure_ascii=False)}")
        content = "\n".join(hints)
        return content if len(hints) > 1 else None

    def _merge_results(
        self,
        rule_result: Optional[RuleResult],
        llm_parsed: Dict[str, Any],
        query: str,
    ) -> tuple[Dict[str, Any], IntentCode, Dict[str, Any]]:
        """合并规则结果与大模型 JSON，并执行后置校验与补全。"""
        # 1. 规范化大模型候选列表，方便与规则结果做精度比较。
        llm_parsed = llm_parsed or {}
        raw_result = llm_parsed.get("result")
        llm_event_confidence = 0.0
        try:
            llm_event_confidence = float(llm_parsed.get("event_confidence", 0) or 0)
        except (TypeError, ValueError):
            llm_event_confidence = 0.0

        def _safe_float(raw: Any) -> Optional[float]:
            if raw is None:
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        candidate_entries: list[dict[str, Any]] = []
        for item in llm_parsed.get("intent_candidates", []) or []:
            if not isinstance(item, dict):
                continue
            code_value = item.get("intent_code") or item.get("intent")
            try:
                candidate_code = IntentCode(code_value)
            except Exception:  # noqa: BLE001
                continue
            candidate_definition = INTENT_DEFINITIONS.get(candidate_code)
            if not candidate_definition:
                continue
            candidate_result = (item.get("result") or candidate_definition.result or "").strip()
            candidate_target = (item.get("target") or "").strip()
            candidate_parsed_time = (item.get("parsed_time") or "").strip()
            candidate_event = (item.get("event") or "").strip()
            candidate_status = (item.get("status") or "").strip()
            candidate_reason = (item.get("reason") or item.get("reasoning") or "").strip()
            candidate_time_text = (item.get("time_text") or "").strip()
            try:
                candidate_conf = float(item.get("confidence", 0) or 0)
            except (TypeError, ValueError):
                candidate_conf = 0.0
            try:
                candidate_event_conf = float(item.get("event_confidence", 0) or 0)
            except (TypeError, ValueError):
                candidate_event_conf = 0.0
            try:
                candidate_status_conf = float(item.get("status_confidence", 0) or 0)
            except (TypeError, ValueError):
                candidate_status_conf = 0.0
            candidate_time_conf = _safe_float(item.get("time_confidence"))
            candidate_entry = {
                "intent_code": candidate_code,
                "result": candidate_result,
                "target": candidate_target,
                "parsed_time": candidate_parsed_time,
                "event": candidate_event,
                "event_confidence": max(0.0, min(candidate_event_conf, 1.0)),
                "status": candidate_status,
                "status_confidence": max(0.0, min(candidate_status_conf, 1.0)),
                "confidence": max(0.0, min(candidate_conf, 1.0)),
                "reason": candidate_reason,
                "time_text": candidate_time_text,
                "time_confidence": candidate_time_conf,
            }
            candidate_entries.append(candidate_entry)

        selected_candidate: dict[str, Any] | None = None
        llm_top_candidate_code: IntentCode | None = None
        llm_top_candidate_result: Optional[str] = None
        if candidate_entries:
            candidate_entries.sort(key=lambda c: c["confidence"], reverse=True)
            top_candidate = candidate_entries[0]
            llm_top_candidate_code = top_candidate["intent_code"]
            llm_top_candidate_result = top_candidate.get("result", "")
            selected_candidate = dict(top_candidate)

        # 2. 将规则识别的结果转换为候选，必要时用于纠偏。
        rule_promoted = False
        rule_candidate: dict[str, Any] | None = None
        override_from_code: Optional[IntentCode] = None
        if rule_result:
            rule_conf = rule_result.confidence
            try:
                rule_conf_value = float(rule_conf) if rule_conf is not None else 0.95
            except (TypeError, ValueError):
                rule_conf_value = 0.95
            rule_candidate = {
                "intent_code": rule_result.intent_code,
                "result": (rule_result.result or "").strip(),
                "target": (rule_result.target or "").strip(),
                "confidence": rule_conf_value,
                "reason": (rule_result.reasoning or "").strip(),
            }

        if self._should_promote_rule_candidate(selected_candidate, rule_result):
            if selected_candidate:
                override_from_code = selected_candidate.get("intent_code")
            selected_candidate = rule_candidate
            rule_promoted = True
        elif not selected_candidate and rule_candidate:
            selected_candidate = rule_candidate

        intent_code = (
            selected_candidate["intent_code"]
            if selected_candidate
            else self._resolve_intent_code(rule_result, llm_parsed)
        )
        definition = INTENT_DEFINITIONS.get(intent_code, INTENT_DEFINITIONS[IntentCode.UNKNOWN])

        # 结果优先级：规则细分 > LLM 合法枚举 > 枚举默认值 > 原始 LLM 结果
        weather_info: Dict[str, Any] = llm_parsed.get("weather_info") or {}
        location_info = weather_info.get("location") or {}
        datetime_info = weather_info.get("datetime") or {}
        needs_realtime_data = bool(weather_info.get("needs_realtime_data", False))

        weather_summary = weather_info.get("weather_summary") or llm_parsed.get("weather_summary")
        weather_condition = weather_info.get("weather_condition") or llm_parsed.get("weather_condition")
        if rule_result and getattr(rule_result, "weather_condition", None):
            weather_condition = rule_result.weather_condition

        def _to_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        location_confidence = _to_float(location_info.get("confidence"))
        datetime_confidence = _to_float(datetime_info.get("confidence"))
        weather_confidence = _to_float(weather_info.get("weather_confidence"))
        weather_evidence = weather_info.get("weather_evidence") or llm_parsed.get("weather_evidence")

        location_name = (location_info.get("name") or "").strip()
        numeral_tokens = {"一","二","三","四","五","六","七","八","九","十","零","〇"}
        if not location_name or len(location_name) < 2 or any(char.isdigit() for char in location_name) or (
            len(location_name) == 2 and location_name.endswith("市") and location_name[0] in numeral_tokens
        ):
            location_name = self._default_city
            location_confidence = 0.5
            location_info = {
                "name": location_name,
                "type": "city",
                "confidence": location_confidence,
                "source": "default",
            }
        elif not all("\u4e00" <= ch <= "\u9fff" or ch.isalpha() for ch in location_name):
            location_name = self._default_city
            location_confidence = 0.5
            location_info = {
                "name": location_name,
                "type": "city",
                "confidence": location_confidence,
                "source": "default",
            }

        raw_target_iso = datetime_info.get("iso") or ""
        target_iso = raw_target_iso.strip() if isinstance(raw_target_iso, str) else ""
        if target_iso:
            try:
                datetime.fromisoformat(target_iso)
            except ValueError:
                target_iso = ""

        weather_detail: Optional[Dict[str, Any]] = {
            "location": location_name,
            "location_type": location_info.get("type", ""),
            "location_confidence": location_confidence,
            "target_date": target_iso or None,
            "target_date_text": datetime_info.get("text", ""),
            "target_date_confidence": datetime_confidence,
            "needs_realtime_data": needs_realtime_data,
        }
        if location_info.get("source") == "default":
            weather_detail["location_source"] = "default"

        llm_result = llm_parsed.get("result")
        candidate_result = selected_candidate.get("result") if selected_candidate else None

        if selected_candidate and candidate_result in self._allowed_results:
            result = candidate_result
        elif selected_candidate and candidate_result and candidate_result not in self._allowed_results:
            result = definition.result if definition.result in self._allowed_results else ""
        elif rule_result and rule_result.result:
            result = rule_result.result
        elif llm_result and llm_result in self._allowed_results:
            result = llm_result
        elif intent_code != IntentCode.UNKNOWN:
            result = definition.result
        else:
            result = llm_result or ""

        def _contains_chat_keyword(text: str) -> bool:
            return any(token in (text or "") for token in CHAT_KEYWORDS)

        # 切歌兜底归一：若意图或候选属于娱乐/音乐控制且命中关键词，则强制 result 归一
        def _contains_prev(text: str) -> bool:
            return any(token in (text or "") for token in ["上一首", "上一曲", "上一个", "上首", "往前一首", "上一段", "上一节"])

        def _contains_next(text: str) -> bool:
            return any(token in (text or "") for token in ["下一首", "下一曲", "下一个", "下首", "往后一首", "下一段", "下一节"])

        if intent_code in {
            IntentCode.ENTERTAINMENT_GENERAL,
            IntentCode.ENTERTAINMENT_MUSIC,
            IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC,
            IntentCode.ENTERTAINMENT_RESUME,
            IntentCode.ENTERTAINMENT_PREV_TRACK,
            IntentCode.ENTERTAINMENT_NEXT_TRACK,
        }:
            if _contains_prev(query):
                intent_code = IntentCode.ENTERTAINMENT_PREV_TRACK
                result = "上一首"
            elif _contains_next(query):
                intent_code = IntentCode.ENTERTAINMENT_NEXT_TRACK
                result = "下一首"

        if intent_code == IntentCode.CHAT or result == "语音陪伴或聊天":
            if _contains_chat_keyword(query):
                # 显式聊天请求 → 保持 CHAT 意图，走聊天功能
                pass
            elif _is_social_greeting(query):
                # 社交问候 → 直接回复，不触发功能、不澄清
                function_analysis = {
                    "result": "",
                    "target": "",
                    "event": None,
                    "status": None,
                    "confidence": 0.85,
                    "need_clarify": False,
                    "clarify_message": None,
                    "reasoning": "social_greeting",
                }
                return function_analysis, intent_code, {}
            else:
                # LLM 判定为对话型 — 检查是否有可用的 reply
                llm_chat_reply = (llm_parsed.get("reply") or "").strip()
                if llm_chat_reply:
                    # 有 reply → 第三层：直接回答（问答/闲聊）
                    function_analysis = {
                        "result": "",
                        "target": "",
                        "event": None,
                        "status": None,
                        "confidence": 0.80,
                        "need_clarify": False,
                        "clarify_message": None,
                        "reasoning": "chat_or_qa_with_reply",
                    }
                    return function_analysis, intent_code, {}
                else:
                    # 无 reply → 第二层：澄清
                    intent_code = IntentCode.UNKNOWN
                    result = ""
                    function_analysis = {
                        "result": "",
                        "target": "",
                        "event": None,
                        "status": None,
                        "confidence": 0.0,
                        "need_clarify": True,
                        "clarify_message": "我可以陪您聊天，也可以帮您处理天气、用药提醒、健康监测、家政等需求，请再具体说说您的想法？",
                        "reasoning": "缺少明确意图，需澄清。",
                    }
                    return function_analysis, intent_code, {}

        candidate_parsed_time = None
        candidate_time_text = ""
        candidate_time_conf = None
        if selected_candidate:
            candidate_parsed_time = (selected_candidate.get("parsed_time") or "").strip()
            candidate_time_text = (selected_candidate.get("time_text") or "").strip()
            candidate_time_conf = selected_candidate.get("time_confidence")
            target = selected_candidate.get("target", "") or ""
            if not target and candidate_parsed_time:
                target = candidate_parsed_time
        else:
            target = llm_parsed.get("target") or ""
            candidate_parsed_time = (llm_parsed.get("parsed_time") or "").strip()
            if not target and candidate_parsed_time:
                target = candidate_parsed_time
        if isinstance(target, str):
            target = target.strip()
        if (not target) and rule_result and rule_result.target is not None:
            target = rule_result.target

        parsed_time_value = candidate_parsed_time or (llm_parsed.get("parsed_time") or "").strip()
        time_text_value = candidate_time_text or (llm_parsed.get("time_text") or "").strip()
        time_confidence = candidate_time_conf
        if time_confidence is None:
            time_confidence = _safe_float(llm_parsed.get("time_confidence"))
        if time_confidence is not None:
            time_confidence = max(0.0, min(time_confidence, 1.0))

        filled_time_from_rule = False
        # 闹钟/提醒：若 LLM 未给出 parsed_time，但规则已解析出 target，则补齐 parsed_time
        if (
            not parsed_time_value
            and rule_result
            and rule_result.intent_code in {IntentCode.ALARM_CREATE, IntentCode.ALARM_REMINDER}
            and rule_result.target
        ):
            candidate_iso = str(rule_result.target).strip()
            try:
                datetime.strptime(candidate_iso, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                candidate_iso = ""
            if candidate_iso:
                parsed_time_value = candidate_iso
                filled_time_from_rule = True
                if not time_text_value:
                    time_text_value = "规则解析"
                if time_confidence is None:
                    time_confidence = 0.92

        time_source = "none"
        if parsed_time_value:
            if filled_time_from_rule:
                time_source = "rule"
            elif time_confidence is not None:
                time_source = "llm" if time_confidence >= TIME_CONFIDENCE_THRESHOLD else "llm_low"
            else:
                time_source = "llm"
        elif rule_result and rule_result.target:
            time_source = "rule"

        time_uncertain = False

        # 事件/状态主要用于闹钟提醒。
        event_source = "none"
        event_marker = None
        candidate_event = None
        candidate_event_conf = 0.0
        candidate_status = None
        candidate_status_conf = 0.0
        if selected_candidate:
            candidate_event = selected_candidate.get("event") or ""
            candidate_event_conf = selected_candidate.get("event_confidence", 0.0) or 0.0
            candidate_status = selected_candidate.get("status") or ""
            candidate_status_conf = selected_candidate.get("status_confidence", 0.0) or 0.0

        event = None
        if candidate_event:
            sanitized = self._sanitize_event_text(candidate_event)
            if self._validate_event_text(sanitized):
                event = sanitized
                if candidate_event_conf >= EVENT_CONFIDENCE_THRESHOLD:
                    event_source = "llm"
                    event_marker = "alarm_details=llm"
                else:
                    event_source = "llm_low_conf"
                    event_marker = "alarm_details=llm_low"

        if event is None and llm_parsed.get("event"):
            sanitized = self._sanitize_event_text(llm_parsed.get("event") or "")
            if self._validate_event_text(sanitized):
                event = sanitized
                if llm_event_confidence >= EVENT_CONFIDENCE_THRESHOLD:
                    event_source = "llm"
                    event_marker = "alarm_details=llm"
                else:
                    event_source = "llm_low_conf"
                    event_marker = "alarm_details=llm_low"

        if event is None and rule_result and rule_result.event:
            sanitized = self._sanitize_event_text(rule_result.event)
            if self._validate_event_text(sanitized):
                event = sanitized
                event_source = "rule"
                event_marker = "alarm_details=rule"

        status = None
        if candidate_status and candidate_status_conf >= 0.5:
            status = candidate_status
        elif llm_parsed.get("status"):
            status = (llm_parsed.get("status") or "").strip()
        elif rule_result and rule_result.status:
            status = rule_result.status

        if selected_candidate:
            confidence = selected_candidate.get("confidence", 0.0)
        else:
            confidence = llm_parsed.get("confidence")
        if confidence is None and rule_result and rule_result.confidence is not None:
            confidence = rule_result.confidence
        if confidence is None:
            if intent_code in ACTIONABLE_INTENTS:
                confidence = 0.8
            elif intent_code == IntentCode.UNKNOWN:
                confidence = 0.3
            else:
                confidence = 0.65
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if rule_result and (not selected_candidate or confidence < self._confidence_threshold):
            rule_conf = rule_result.confidence if rule_result.confidence is not None else 0.95
            confidence = max(confidence, rule_conf)
        confidence = min(max(confidence, 0.0), 1.0)

        need_clarify = bool(llm_parsed.get("need_clarify", False))
        clarify_message = llm_parsed.get("clarify_message") or None
        if rule_result and rule_result.need_clarify:
            need_clarify = True
        if rule_result and rule_result.clarify_message and not clarify_message:
            clarify_message = rule_result.clarify_message

        if intent_code in {IntentCode.ALARM_CREATE, IntentCode.ALARM_REMINDER}:
            if not parsed_time_value:
                need_clarify = True
                if not clarify_message:
                    clarify_message = "我还需要确认具体提醒时间，可以再描述一下吗？"
                time_uncertain = True
            elif time_confidence is not None and time_confidence < TIME_CONFIDENCE_THRESHOLD:
                need_clarify = True
                if not clarify_message:
                    clarify_message = "为了确保提醒准确，可以再确认一下具体时间吗？"
                time_uncertain = True

        reasoning_parts: list[str] = []
        if llm_parsed.get("reasoning"):
            reasoning_parts.append(str(llm_parsed["reasoning"]))
        if selected_candidate and selected_candidate.get("reason"):
            reasoning_parts.append(str(selected_candidate["reason"]))
        if rule_result and rule_result.reasoning:
            reasoning_parts.append(rule_result.reasoning)
        if raw_result and raw_result != result:
            reasoning_parts.append(f"LLM_suggested_result={raw_result}")
        if rule_promoted and rule_result:
            if override_from_code and override_from_code != rule_result.intent_code:
                reasoning_parts.append(
                    f"rule_override={rule_result.intent_code.value}<-{override_from_code.value}"
                )
            else:
                reasoning_parts.append(f"rule_override={rule_result.intent_code.value}")
        if event_source != "none":
            reasoning_parts.append(f"event_source={event_source}")
        if event_marker:
            reasoning_parts.append(event_marker)
        if time_source != "none":
            reasoning_parts.append(f"time_source={time_source}")
        if time_confidence is not None:
            reasoning_parts.append(f"time_confidence={round(time_confidence, 2)}")
        advice = (llm_parsed.get("advice") or "").strip()
        safety_notice = (llm_parsed.get("safety_notice") or "").strip()

        normalized_reasoning: list[str] = []
        seen_reasoning: set[str] = set()
        for part in reasoning_parts:
            cleaned_part = (part or "").strip()
            if not cleaned_part:
                continue
            if cleaned_part in seen_reasoning:
                continue
            seen_reasoning.add(cleaned_part)
            normalized_reasoning.append(cleaned_part)
        reasoning = "；".join(normalized_reasoning) or None

        is_health = self._is_health_related(query, advice, result)
        # 若大模型给出了健康建议但意图落在 UNKNOWN，则按“健康科普”承载建议内容，
        # 避免前端无法路由或误触发澄清流程。
        if advice and is_health and intent_code == IntentCode.UNKNOWN:
            intent_code = IntentCode.HEALTH_EDUCATION
            definition = INTENT_DEFINITIONS[intent_code]
            result = definition.result
            if not target:
                target = query.strip()
            reasoning_parts.append("health_advice_promote")

        if is_health and intent_code not in ACTIONABLE_INTENTS and not safety_notice:
            safety_notice = DEFAULT_SAFETY_NOTICE

        # 模糊症状：交给澄清流程，不直接归入健康科普/监测
        if self._is_vague_symptom_query(query):
            if (
                intent_code == IntentCode.UNKNOWN
                and not advice
                and not safety_notice
                and intent_code not in WEATHER_INTENT_CODES
                and intent_code not in ACTIONABLE_INTENTS
            ):
                intent_code = IntentCode.UNKNOWN
                result = ""
                need_clarify = True
                advice = None
                safety_notice = None
                reasoning_parts.append("vague_symptom_clarify")

        # UNKNOWN 或低置信候选：保持 need_clarify；若缺少澄清话术则补一个通用版本
        if intent_code == IntentCode.UNKNOWN:
            need_clarify = True
        if selected_candidate and selected_candidate.get("confidence", 0.0) < self._confidence_threshold and intent_code not in ACTIONABLE_INTENTS:
            need_clarify = True

        if intent_code in ACTIONABLE_INTENTS and confidence >= self._confidence_threshold and not time_uncertain:
            need_clarify = False
            clarify_message = None

        if need_clarify and not clarify_message:
            clarify_message = ""

        if result and result not in self._allowed_results:
            reasoning = (reasoning + "；" if reasoning else "") + "result 已校正为允许列表。"
            result = definition.result if intent_code != IntentCode.UNKNOWN else ""
            if not result:
                need_clarify = True

        # 澄清阶段完全依赖 LLM 提供的 clarify_message/reply，不做本地兜底
        # 若 LLM 未提供，clarify_message 可保持为空，由上游直接返回空或回复内容

        if intent_code in ACTIONABLE_INTENTS:
            advice = None
            safety_notice = None

        if intent_code not in WEATHER_INTENT_CODES:
            weather_summary = None
            weather_condition = None
            weather_confidence = None
            weather_evidence = None
            needs_realtime_data = False
            weather_detail = None
        else:
            if weather_detail and not any(token in query for token in ["市", "县", "区", "省", "镇", "乡", "村", "州"]):
                weather_detail["location"] = self._default_city
                weather_detail["location_confidence"] = max(weather_detail.get("location_confidence") or 0.0, 0.5)
                weather_detail["location_source"] = "default"
                if weather_summary:
                    weather_summary = weather_summary.replace(location_name, self._default_city)

        function_analysis = {
            "result": result,
            "target": target,
            "event": event,
            "status": status,
            "parsed_time": parsed_time_value or None,
            "time_text": time_text_value or None,
            "time_confidence": time_confidence,
            "time_source": time_source if time_source != "none" else None,
            "confidence": confidence,
            "need_clarify": need_clarify,
            "clarify_message": clarify_message,
            "reasoning": reasoning,
            "advice": advice or None,
            "safety_notice": safety_notice or None,
            "weather_condition": weather_condition,
            "weather_summary": weather_summary,
            "weather_detail": weather_detail,
            "weather_confidence": weather_confidence,
            "weather_evidence": weather_evidence,
            "weather_needs_realtime": needs_realtime_data,
        }

        merge_meta = {
            "rule_promoted": rule_promoted,
            "llm_top_intent": llm_top_candidate_code.value if llm_top_candidate_code else None,
            "llm_top_result": llm_top_candidate_result,
            "event_source": event_source,
            "time_source": time_source,
            "weather_needs_realtime": needs_realtime_data,
        }

        return function_analysis, intent_code, merge_meta

    def _sanitize_event_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = str(text).strip()
        for token in sorted(EVENT_PREFIX_TOKENS, key=len, reverse=True):
            if cleaned.startswith(token):
                cleaned = cleaned[len(token):].lstrip()
                break
        changed = True
        while cleaned and changed:
            changed = False
            for token in sorted(EVENT_TIME_TOKENS, key=len, reverse=True):
                if cleaned.startswith(token):
                    cleaned = cleaned[len(token):].lstrip()
                    changed = True
        cleaned = cleaned.lstrip("，,。.:：;；的 和")
        cleaned = cleaned.rstrip("，,。.:：;； ")
        return cleaned.strip()

    def _validate_event_text(self, text: Optional[str]) -> bool:
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) < EVENT_MIN_LENGTH:
            return False
        if stripped in EVENT_TIME_TOKENS:
            return False
        if stripped in EVENT_PREFIX_TOKENS:
            return False
        for token in EVENT_TIME_TOKENS:
            if stripped.startswith(token) and len(stripped) <= len(token) + 1:
                return False
        if not any("\u4e00" <= ch <= "\u9fff" or ch.isalpha() for ch in stripped):
            return False
        return True

    def _should_promote_rule_candidate(
        self,
        selected_candidate: Optional[dict[str, Any]],
        rule_result: Optional[RuleResult],
    ) -> bool:
        """判断是否需要将规则结果提升为主要候选。"""
        if rule_result is None:
            return False
        if selected_candidate is None:
            return True

        candidate_code: IntentCode = selected_candidate["intent_code"]
        rule_code = rule_result.intent_code

        if candidate_code == rule_code:
            return False

        if candidate_code == IntentCode.UNKNOWN:
            return True

        promote_targets = INTENT_OVERRIDE_MAP.get(candidate_code, set())
        if rule_code not in promote_targets:
            return False

        candidate_conf = selected_candidate.get("confidence", 0.0) or 0.0
        try:
            candidate_conf = float(candidate_conf)
        except (TypeError, ValueError):
            candidate_conf = 0.0

        rule_conf = rule_result.confidence if rule_result.confidence is not None else 0.95
        try:
            rule_conf = float(rule_conf)
        except (TypeError, ValueError):
            rule_conf = 0.95

        return rule_conf + RULE_PROMOTION_TOLERANCE >= candidate_conf

    def _coerce_settings_target(
        self,
        *,
        query: str,
        function_analysis: Dict[str, Any],
        candidate_rule_result: Optional[RuleResult],
    ) -> None:
        """对音量/亮度的 target 做强约束纠偏，保证线上可直接执行。"""
        result = (function_analysis.get("result") or "").strip()
        if result not in SETTINGS_RESULTS:
            return

        text = (query or "").strip()
        if not text:
            return

        raw_target = function_analysis.get("target")
        target = str(raw_target).strip() if raw_target is not None else ""

        changed = False
        markers: list[str] = []

        def _append_marker(marker: str) -> None:
            if marker and marker not in markers:
                markers.append(marker)

        def _set_target(new_target: str, marker: str) -> None:
            nonlocal changed, target
            new_target = (new_target or "").strip()
            if new_target and new_target != target:
                function_analysis["target"] = new_target
                target = new_target
                changed = True
                _append_marker(marker)

        def _set_result(new_result: str, marker: str) -> None:
            nonlocal changed, result
            new_result = (new_result or "").strip()
            if new_result and new_result != result and new_result in SETTINGS_RESULTS:
                function_analysis["result"] = new_result
                result = new_result
                changed = True
                _append_marker(marker)

        def _boost_confidence(boost: float = 0.85) -> None:
            nonlocal changed
            existing = function_analysis.get("confidence")
            try:
                numeric_conf = float(existing) if existing is not None else 0.0
            except (TypeError, ValueError):
                numeric_conf = 0.0
            if numeric_conf < boost:
                function_analysis["confidence"] = boost
                changed = True

        def _finalize() -> None:
            """写回标记与置信度，便于排查线上误判。"""
            if markers:
                reasoning = (function_analysis.get("reasoning") or "").strip()
                marker_text = "；".join(markers)
                function_analysis["reasoning"] = f"{reasoning}；{marker_text}" if reasoning else marker_text
            if changed:
                _boost_confidence()

        abs_value = extract_settings_absolute_value(text)
        if abs_value is not None:
            # 绝对设置：强制 target=0~100 的数字字符串（不带 %）
            _set_target(abs_value, f"settings_target=absolute:{abs_value}")
            # 若规则也解析到绝对值且给出了方向词，则允许用规则结果纠正“调高/调低”
            if (
                candidate_rule_result
                and candidate_rule_result.result in SETTINGS_RESULTS
                and str(candidate_rule_result.target or "").strip() == abs_value
            ):
                _set_result(candidate_rule_result.result, f"settings_result=rule:{candidate_rule_result.result}")
            _finalize()
            return

        desired_sign = "+" if result in SETTINGS_UP_RESULTS else "-"

        explicit_delta = extract_settings_relative_delta(text)
        if explicit_delta is not None and explicit_delta <= 0:
            explicit_delta = None
        fallback_amount = explicit_delta or 10

        def _format_delta(sign: str, amount: int) -> str:
            amount = max(0, min(int(amount), 100))
            return f"{sign}{amount}"

        def _is_valid_absolute_value(value: str) -> bool:
            if not value.isdigit():
                return False
            try:
                parsed = int(value)
            except ValueError:
                return False
            return 0 <= parsed <= 100

        def _parse_delta(value: str) -> Optional[tuple[str, int]]:
            match = re.fullmatch(r"(?P<sign>[+-])\s*(?P<num>\d{1,3})\s*(?:[%％])?", value)
            if not match:
                return None
            sign = match.group("sign")
            try:
                num = int(match.group("num"))
            except (TypeError, ValueError):
                return None
            if not (0 <= num <= 100):
                return None
            return sign, num

        # 相对调节：target 必须是 “+N/-N”，并且 result 与符号保持一致。
        if not target:
            _set_target(_format_delta(desired_sign, fallback_amount), "settings_target=delta_default")
            _finalize()
            return

        target_candidate = target.replace("％", "%").strip()

        parsed_delta = _parse_delta(target_candidate)
        if parsed_delta:
            sign, amount = parsed_delta
            normalized = _format_delta(sign, amount)
            _set_target(normalized, f"settings_target=delta_normalized:{normalized}")
            # 符号与 result 不一致时，以符号为准纠正 result（避免 target=-10 但 result=调高）
            if sign == "+" and result in SETTINGS_DOWN_RESULTS:
                _set_result("声音调高" if result.startswith("声音") else "亮度调高", "settings_result=sign_fix")
            elif sign == "-" and result in SETTINGS_UP_RESULTS:
                _set_result("声音调低" if result.startswith("声音") else "亮度调低", "settings_result=sign_fix")
            _finalize()
            return

        # 模型有时会输出 “20%/30” 等绝对值，但语句并非绝对设置；为避免线上误当绝对值执行，
        # 这里统一回退为相对幅度（静音/最大音量通常会在 result 上体现为调低/调高，且 target 也应为 0/100）。
        if _is_valid_absolute_value(target_candidate):
            is_plausible_extreme = (
                (target_candidate == "0" and result in SETTINGS_DOWN_RESULTS)
                or (target_candidate == "100" and result in SETTINGS_UP_RESULTS)
            )
            if not is_plausible_extreme:
                _set_target(_format_delta(desired_sign, fallback_amount), "settings_target=delta_from_absolute")
            _finalize()
            return

        # 兜底：任何不符合规范的 target 都回退为默认幅度
        _set_target(_format_delta(desired_sign, fallback_amount), "settings_target=delta_fallback")
        _finalize()

    async def _resolve_user_target(
        self,
        query: str,
        function_analysis: Dict[str, Any],
        conversation_state: ConversationState,
        meta: Dict[str, Any],
    ) -> None:
        candidates = self._extract_user_candidates(meta, conversation_state)
        if not candidates:
            return

        result = (function_analysis.get("result") or "").strip()
        current_target = (function_analysis.get("target") or "").strip()

        requires_target = result in RESULTS_REQUIRING_USER

        if not requires_target and not result:
            last_fa = conversation_state.last_function_analysis or {}
            last_result = (last_fa.get("result") or "").strip()
            if last_result in RESULTS_REQUIRING_USER:
                requires_target = True
                result = last_result
                function_analysis["result"] = last_result

        if not requires_target:
            return

        if current_target:
            # 如果当前 target 不在候选名单，尝试用候选覆盖（优先单一候选或模糊匹配）
            if current_target in candidates and self._looks_like_name(current_target):
                conversation_state.last_selected_user = current_target
                return
            # 当前 target 不是候选用户（例如“我的家庭/血压测量”），清空以便触发后续覆盖/二次询问
            function_analysis["target"] = ""
            current_target = ""  # 允许后续覆盖

        candidate_name = self._extract_candidate_name(query)
        if not candidate_name:
            # 无法从语句提取姓名时，若仅有单一候选，则直接采用用户提供的候选
            if len(candidates) == 1:
                matched = candidates[0]
                function_analysis["target"] = matched
                function_analysis["need_clarify"] = False
                function_analysis["clarify_message"] = None
                existing_confidence = function_analysis.get("confidence")
                try:
                    numeric_conf = float(existing_confidence) if existing_confidence is not None else 0.0
                except (TypeError, ValueError):
                    numeric_conf = 0.0
                function_analysis["confidence"] = max(numeric_conf, 0.85)
                conversation_state.last_selected_user = matched
                reasoning = function_analysis.get("reasoning") or ""
                source_note = f"user_target={matched}"
                function_analysis["reasoning"] = f"{reasoning}；{source_note}" if reasoning else source_note
            return

        matched = None
        if candidate_name in candidates:
            matched = candidate_name
        else:
            matched = self._fuzzy_match_candidate(candidate_name, candidates)
        if not matched and len(candidates) == 1:
            matched = candidates[0]
        if not matched:
            return

        function_analysis["target"] = matched
        function_analysis["need_clarify"] = False
        function_analysis["clarify_message"] = None
        existing_confidence = function_analysis.get("confidence")
        try:
            numeric_conf = float(existing_confidence) if existing_confidence is not None else 0.0
        except (TypeError, ValueError):
            numeric_conf = 0.0
        function_analysis["confidence"] = max(numeric_conf, 0.85)
        conversation_state.last_selected_user = matched
        # 记录来源，便于追踪
        reasoning = function_analysis.get("reasoning") or ""
        source_note = f"user_target={matched}"
        function_analysis["reasoning"] = f"{reasoning}；{source_note}" if reasoning else source_note

    def _extract_user_candidates(
        self,
        meta: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> List[str]:
        raw_candidates = meta.get("user_candidates")
        candidates: List[str] = []
        if isinstance(raw_candidates, str):
            candidates = [item.strip() for item in raw_candidates.split(",") if item.strip()]
        elif isinstance(raw_candidates, list):
            candidates = [str(item).strip() for item in raw_candidates if str(item).strip()]

        if not candidates:
            candidates = conversation_state.user_candidates
        if candidates and candidates != conversation_state.user_candidates:
            conversation_state.user_candidates = candidates
        return candidates

    @staticmethod
    def _looks_like_name(text: str) -> bool:
        """粗略判断字符串是否像人名，用于过滤 '血压测量' 这类非人名 target。"""
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) <= 1 or len(stripped) > 8:
            return False
        return any("\u4e00" <= ch <= "\u9fff" or ch.isalpha() for ch in stripped)

    @staticmethod
    def _extract_candidate_name(query: str) -> Optional[str]:
        cleaned = sanitize_person_name(query) or query.strip()
        if not cleaned:
            return None
        keywords = ["监测", "评估", "检测", "打开", "设置", "提醒", "帮我", "我要", "请", "联系"]
        if any(keyword in query for keyword in keywords) and len(cleaned) < len(query.strip()):
            return None
        return cleaned

    @staticmethod
    def _fuzzy_match_candidate(name: str, candidates: List[str]) -> Optional[str]:
        if not name or not candidates:
            return None
        best_match = None
        best_score = -1.0
        for candidate in candidates:
            score = SequenceMatcher(None, name, candidate).ratio()
            if score > best_score:
                best_score = score
                best_match = candidate
        return best_match if best_match else None

    async def _refine_content_target(
        self,
        intent_code: IntentCode,
        query: str,
        function_analysis: Dict[str, Any],
    ) -> None:
        if not self._target_refiner.supports(intent_code):
            return
        initial_target = (function_analysis.get("target") or "").strip()
        result = (function_analysis.get("result") or "").strip()
        if not result:
            return

        refinement = await self._target_refiner.refine(
            intent_code=intent_code,
            query=query,
            initial_target=initial_target,
        )
        refined_target = refinement.target
        if not refined_target or refined_target == initial_target:
            return

        function_analysis["target"] = refined_target
        existing_confidence = function_analysis.get("confidence")
        try:
            numeric_conf = float(existing_confidence) if existing_confidence is not None else 0.0
        except (TypeError, ValueError):
            numeric_conf = 0.0
        boost = 0.9 if refinement.source == "llm" else 0.85
        function_analysis["confidence"] = max(numeric_conf, boost)

        marker = f"target_calibrated={refinement.source}:{refined_target}"
        reasoning = function_analysis.get("reasoning")
        function_analysis["reasoning"] = f"{reasoning}；{marker}" if reasoning else marker

    def _resolve_intent_code(
        self,
        rule_result: Optional[RuleResult],
        llm_parsed: Dict[str, Any],
    ) -> IntentCode:
        """确定最终意图编号，优先使用大模型结果，否则回退规则。"""
        intent_code_value = llm_parsed.get("intent_code")
        if intent_code_value:
            try:
                code = IntentCode(intent_code_value)
                if code == IntentCode.UNKNOWN and rule_result:
                    return rule_result.intent_code
                return code
            except ValueError:
                logger.debug("invalid intent_code from LLM", value=intent_code_value)
        if rule_result:
            return rule_result.intent_code
        return IntentCode.UNKNOWN

    def _should_clarify(self, function_analysis: Dict[str, Any]) -> bool:
        """判断当前轮是否仍需向用户进行澄清确认。"""
        if function_analysis.get("need_clarify"):
            return True
        confidence = function_analysis.get("confidence")
        if confidence is None:
            return False
        return confidence < self._confidence_threshold

    def _append_reasoning_marker(self, function_analysis: Dict[str, Any], marker: str) -> None:
        reasoning = (function_analysis.get("reasoning") or "").strip()
        if not marker:
            return
        if marker in reasoning:
            return
        function_analysis["reasoning"] = f"{reasoning}；{marker}" if reasoning else marker

    def _build_local_clarify_message(
        self,
        *,
        query: str,
        function_analysis: Dict[str, Any],
        conversation_state: ConversationState,
        candidate_rule_result: Optional[RuleResult],
    ) -> str:
        text = (query or "").strip()
        rounds = 1
        if conversation_state and getattr(conversation_state, "pending_clarification", False):
            rounds = min((getattr(conversation_state, "clarify_rounds", 0) or 0) + 1, 3)

        def finalize(options: list[str], best_guess: str = "") -> str:
            clean_options = [item.strip() for item in options if item and item.strip()]
            guess = (best_guess or (clean_options[0] if clean_options else "")).strip()
            if rounds >= 3:
                if clean_options:
                    numbered = "，".join(f"回复{idx + 1}{item}" for idx, item in enumerate(clean_options[:3]))
                    if guess:
                        return f"我先按最像的理解，您可能是想{guess}。如果不是，请{numbered}。"
                    return f"我先帮您缩小范围，请{numbered}。"
                return "我先帮您缩小范围：回复1直接回答问题，回复2打开小雅功能，回复3继续描述一下。"
            if len(clean_options) >= 2:
                return f"您是想{clean_options[0]}，还是{clean_options[1]}？"
            if clean_options:
                return f"您是想{clean_options[0]}吗？"
            return "我还没完全听明白。您是想让我直接回答问题，还是帮您打开某个小雅功能？可以再说具体一点。"

        rule_guess = ""
        if candidate_rule_result and getattr(candidate_rule_result, "result", None):
            rule_guess = f"打开{candidate_rule_result.result}"

        if any(token in text for token in ["眯一会", "亮着", "屏幕先灭", "先灭", "熄灭", "别亮了"]):
            return finalize(["帮您息屏", "把屏幕亮度调低一点"], "帮您息屏")
        if any(token in text for token in ["天气", "下雨", "带伞", "雨伞", "雨具", "阵雨", "晒", "冷不冷", "热不热", "潮", "外面"]):
            return finalize(["查天气", "查日期或节日"], rule_guess or "查天气")
        if any(token in text for token in ["几点", "现在时间", "当前时间", "啥时辰", "什么时辰", "时辰"]):
            return finalize(["报当前时间", "查日期或农历"], rule_guess or "报当前时间")
        if any(token in text for token in ["农历", "黄历", "节气", "节日", "腊八", "几号", "日期"]):
            return finalize(["查日期和万年历", "报当前时间"], rule_guess or "查日期和万年历")
        if any(token in text for token in ["血压", "血糖", "血氧", "心率", "睡眠", "体温", "尿酸", "血脂"]):
            monitor_guess = rule_guess or "打开健康监测"
            return finalize([monitor_guess, "先听相关健康建议"], monitor_guess)
        if any(token in text for token in ["评估", "体况", "画像", "指数", "总结", "留个档", "留档"]):
            best_guess = "看健康画像" if any(token in text for token in ["画像", "总结", "留个档", "留档"]) else "做健康评估"
            return finalize(["做健康评估", "看健康画像"], rule_guess or best_guess)
        if any(token in text for token in ["专家", "名医", "医生", "大夫"]) and any(token in text for token in ["远程", "预约", "问问", "看看", "看病", "老毛病"]):
            return finalize(["预约名医问诊", "联系家庭医生"], rule_guess or "预约名医问诊")
        if any(token in text for token in ["相册", "照片", "拍的", "拍的小"]):
            return finalize(["打开相册看看照片"], rule_guess or "打开相册看看照片")
        if any(token in text for token in ["闺女", "儿子", "女儿", "家人", "老伴", "妈妈", "爸爸", "外孙", "孙女", "语音", "视频", "打给"]):
            best_guess = "发起视频通话" if "视频" in text else "发起语音通话"
            return finalize(["发起语音通话", "发起视频通话"], rule_guess or best_guess)
        if any(token in text for token in ["评书", "戏曲", "听书", "小说", "音乐", "听歌", "娱乐"]):
            best_guess = "听评书或戏曲" if any(token in text for token in ["评书", "戏曲"]) else "听书" if any(token in text for token in ["听书", "小说"]) else "听音乐"
            return finalize(["听评书或戏曲", "听书", "听音乐"], rule_guess or best_guess)
        if any(token in text for token in ["商城", "买", "购买", "零食", "拐杖", "商品"]):
            best_guess = "查看健康食疗产品" if any(token in text for token in ["零食"]) else "查看适老化用品" if any(token in text for token in ["拐杖"]) else "打开商城看看"
            return finalize(["打开商城看看", "查看适老化用品", "查看健康食疗产品"], rule_guess or best_guess)
        if any(token in text for token in ["头晕", "心慌", "过敏", "咳嗽", "发热", "发烧", "疼", "痛", "不舒服"]):
            return finalize(["直接说说健康建议", "打开健康监测功能", "联系医生咨询"], "直接说说健康建议")
        if rule_guess:
            return finalize([rule_guess, "直接回答问题", "换个小雅功能"], rule_guess)
        return finalize(["直接回答问题", "打开小雅功能", "继续描述一下"], "直接回答问题")

    def _apply_toc_contract(
        self,
        query: str,
        intent_code: IntentCode,
        function_analysis: Dict[str, Any],
    ) -> None:
        """将内部意图归一到 ToC 面向前端的公开返回契约。"""
        if intent_code != IntentCode.HEALTH_EDUCATION:
            return
        if not self._is_health_education_broadcast_only_query(query):
            return
        function_analysis["result"] = ""
        function_analysis["need_clarify"] = False
        function_analysis["clarify_message"] = None

    def _is_health_education_broadcast_only_query(self, query: str) -> bool:
        text = (query or "").strip()
        if not text:
            return False
        content_tokens = ["打开", "进入", "查看", "打开页面", "打开科普", "播放", "看", "看看", "课程", "视频", "教学", "学"]
        if any(token in text for token in content_tokens):
            return False
        question_tokens = ["讲讲", "怎么", "怎么办", "如何", "判断", "知识", "建议", "小贴士", "注意点啥", "说说", "了解", "吃什么", "注意什么"]
        if any(token in text for token in question_tokens):
            return True
        return "健康科普" in text and "页面" not in text

    def _default_reply(self, function_analysis: Dict[str, Any]) -> str:
        """当大模型未返回 reply 字段时的兜底自然语言响应。"""
        result = function_analysis.get("result")
        advice = function_analysis.get("advice")
        safety = function_analysis.get("safety_notice")
        event = (function_analysis.get("event") or "").strip()
        status = (function_analysis.get("status") or "").strip()
        target = (function_analysis.get("target") or "").strip()
        parts = [part for part in [advice, safety] if part]
        if function_analysis.get("need_clarify"):
            clarify = function_analysis.get("clarify_message") or ""
            parts = [part for part in [advice, safety, clarify] if part]
            return " ".join(parts).strip()
        if result == "取消闹钟":
            if target:
                parts.append(f"好的，我来帮您取消{target}的闹钟。")
            else:
                parts.append("您想取消哪一个闹钟？")
            return " ".join(part for part in parts if part).strip()
        if result == "用药计划":
            if target and function_analysis.get("parsed_time"):
                parts.append(f"好的，我已为您添加{target}的用药计划。")
            else:
                parts.append("好的，我已为您打开用药计划。")
            return " ".join(part for part in parts if part).strip()
        if result == "小雅预约":
            parts.append("好的，我已为您打开小雅预约。")
            return " ".join(part for part in parts if part).strip()
        if result == "小雅电影":
            parts.append("好的，我已为您打开小雅电影。")
            return " ".join(part for part in parts if part).strip()
        if result == "娱乐管家":
            parts.append("好的，我已为您打开娱乐管家。")
            return " ".join(part for part in parts if part).strip()
        if result == "家庭医生":
            if target:
                parts.append(f"好的，我来帮您联系{target}的家庭医生。")
            else:
                parts.append("好的，我已为您打开家庭医生。")
            return " ".join(part for part in parts if part).strip()
        if result == "小雅教育":
            if target:
                parts.append(f"好的，我已为您打开{target}相关的小雅教育内容。")
            else:
                parts.append("好的，我已为您打开小雅教育。")
            return " ".join(part for part in parts if part).strip()
        if result == "健康科普":
            parts.append("好的，我已为您打开健康科普。")
            return " ".join(part for part in parts if part).strip()
        if not result and target:
            parts.append(f"我来给您讲讲{target}。")
            return " ".join(part for part in parts if part).strip()
        schedule_bits = [bit for bit in [status, target] if bit] if result in {"新增闹钟"} else []
        schedule_desc = "、".join(schedule_bits)
        if result:
            if schedule_desc and event:
                parts.append(f"好的，我会在{schedule_desc}提醒您{event}。")
            elif schedule_desc:
                parts.append(f"好的，我会在{schedule_desc}为您处理{result}。")
            elif event:
                parts.append(f"好的，我会提醒您{event}。")
            else:
                parts.append(f"好的，我会为您处理{result}相关的请求。")
        elif event:
            parts.append(f"好的，我会记得提醒您{event}。")
        if not parts:
            parts.append("好的，我在这里，随时为您服务。")
        return " ".join(parts).strip()

    def _is_health_related(self, query: str, advice: str | None, result: str | None) -> bool:
        """根据关键字快速判断当前语句是否属于健康相关场景。"""
        combined = (query or '') + (advice or '') + (result or '')
        return any(keyword in combined for keyword in HEALTH_KEYWORDS)

    def _is_vague_symptom_query(self, query: str) -> bool:
        """判断是否为模糊的身体感受描述，缺少明确疾病/指标信息。"""
        q = query.lower()
        vague_tokens = ["好热", "好冷", "不舒服", "难受", "发困", "乏力", "头晕", "恶心", "闷得慌", "没精神"]
        strong_health_markers = ["发烧", "体温", "度", "血压", "血糖", "心率", "心电", "用药", "药", "医生", "医院", "咳", "疼", "痛", "呕吐", "拉肚子"]
        has_vague = any(tok in q for tok in vague_tokens)
        has_strong = any(tok in q for tok in strong_health_markers)
        return has_vague and not has_strong
