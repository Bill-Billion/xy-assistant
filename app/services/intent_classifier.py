from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
import re
from time import perf_counter
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.conversation import ConversationState
from app.services.intent_definitions import INTENT_DEFINITIONS, IntentCode
from app.services.intent_rules import RuleResult, run_rules
from app.services.llm_client import DoubaoClient
from app.services.target_refiner import TargetRefiner
from app.services.prompt_templates import build_system_prompt, get_allowed_results
from app.utils.time_utils import EAST_EIGHT, now_e8, sanitize_person_name



HEALTH_KEYWORDS = {
    "头晕", "头痛", "血压", "血糖", "血脂", "熬夜", "失眠",
    "感冒", "发烧", "咳嗽", "疼", "不舒服", "痛", "疲劳",
    "药", "治疗", "心脏", "胃", "骨折", "康复", "健康",
}
DEFAULT_SAFETY_NOTICE = (
    "小雅的建议仅供参考，不替代专业医疗意见，如症状持续或加重请及时咨询医生。"
)

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
    IntentCode.ALARM_CREATE,
    IntentCode.ALARM_REMINDER,
    IntentCode.ALARM_VIEW,
}

# LLM 事件解析参数
EVENT_CONFIDENCE_THRESHOLD = 0.6
EVENT_MIN_LENGTH = 2
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
}

# 规则优先映射：当大模型仅识别出泛化意图时，用于提升规则识别的细分意图。
INTENT_OVERRIDE_MAP: dict[IntentCode, set[IntentCode]] = {
    IntentCode.HEALTH_MONITOR_GENERAL: ACTIONABLE_HEALTH_INTENTS - {IntentCode.HEALTH_MONITOR_GENERAL},
    IntentCode.FAMILY_DOCTOR_GENERAL: {
        IntentCode.FAMILY_DOCTOR_CONTACT,
        IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
        IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
    },
    IntentCode.FAMILY_DOCTOR_CONTACT: {
        IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
        IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
    },
    IntentCode.COMMUNICATION_GENERAL: {
        IntentCode.COMMUNICATION_CALL_AUDIO,
        IntentCode.COMMUNICATION_CALL_VIDEO,
    },
    IntentCode.ENTERTAINMENT_GENERAL: {
        IntentCode.ENTERTAINMENT_OPERA,
        IntentCode.ENTERTAINMENT_OPERA_SPECIFIC,
        IntentCode.ENTERTAINMENT_MUSIC,
        IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC,
        IntentCode.ENTERTAINMENT_AUDIOBOOK,
        IntentCode.GAME_DOU_DI_ZHU,
        IntentCode.GAME_CHINESE_CHESS,
        IntentCode.CHAT,
    },
    IntentCode.ENTERTAINMENT_OPERA: {IntentCode.ENTERTAINMENT_OPERA_SPECIFIC},
    IntentCode.ENTERTAINMENT_MUSIC: {IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC},
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
}


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
        self._system_prompt = build_system_prompt()
        self._allowed_results = get_allowed_results()
        self._target_refiner = TargetRefiner(llm_client)

    async def classify(
        self,
        session_id: str,
        query: str,
        meta: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> ClassificationResult:
        """对用户输入进行分类，生成结构化分析结果与回复。"""
        # 先运行规则引擎，获取可能的高置信度提示意图。
        rule_result = run_rules(query, meta)
        logger.debug(
            "rule_result",
            session_id=session_id,
            rule_intent=getattr(rule_result, "intent_code", None),
            rule_target=getattr(rule_result, "target", None),
        )

        llm_response_text = ""
        llm_parsed: dict[str, Any] = {}
        llm_reply: str = ""
        try:
            # 汇总对话历史，保证模型理解当前上下文。
            messages = conversation_state.as_messages()
            reference_message = self._build_reference_message(query, rule_result, meta)
            if reference_message:
                messages.append({"role": "assistant", "content": reference_message})
            messages.append({"role": "user", "content": query})
            classify_llm_start = perf_counter()
            llm_response_text, llm_parsed = await self._llm_client.chat(
                system_prompt=self._system_prompt,
                messages=messages,
                response_format={"type": "json_object"},
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

        function_analysis, intent_code, merge_meta = self._merge_results(rule_result, llm_parsed, query)
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
        alarm_reply_hint = await self._ensure_alarm_details(
            query=query,
            function_analysis=function_analysis,
        )

        reply_message = llm_reply or ""
        if not reply_message and alarm_reply_hint:
            reply_message = alarm_reply_hint

        if self._should_clarify(function_analysis):
            function_analysis["need_clarify"] = True
            if function_analysis.get("clarify_message"):
                reply_message = function_analysis["clarify_message"]
            else:
                clarify_message = "我需要再确认一下，方便详细说说吗？"
                function_analysis["clarify_message"] = clarify_message
                reply_message = clarify_message
        else:
            function_analysis.setdefault("need_clarify", False)
            if not reply_message:
                reply_message = self._default_reply(function_analysis)

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
    ) -> Optional[str]:
        """将规则提示、时间等参考信息打包成辅助消息提供给大模型。"""
        hints: list[str] = []
        hints.append(f"参考信息（仅供参考，请以实际语义为准）")
        hints.append(f"- 当前时间（东八区）：{now_e8().strftime('%Y-%m-%d %H:%M')}" )
        if rule_result:
            hints.append(f"- 规则候选功能：{rule_result.intent_code.value}")
            if rule_result.result:
                hints.append(f"- 候选 result：{rule_result.result}")
            if rule_result.target:
                hints.append(f"- 候选 target：{rule_result.target}")
            if getattr(rule_result, "weather_condition", None):
                hints.append(f"- 关注天气要素：{rule_result.weather_condition}")
        if meta:
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
            selected_candidate = {
                "intent_code": top_candidate["intent_code"],
                "result": top_candidate.get("result", ""),
                "target": top_candidate.get("target", ""),
                "confidence": top_candidate.get("confidence", 0.0),
                "reason": top_candidate.get("reason", ""),
            }

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
        weather_condition = None
        if rule_result and getattr(rule_result, "weather_condition", None):
            weather_condition = rule_result.weather_condition
        else:
            weather_condition = llm_parsed.get("weather_condition")

        weather_summary = llm_parsed.get("weather_summary")
        weather_detail = llm_parsed.get("weather_detail")
        weather_confidence = llm_parsed.get("weather_confidence")
        if weather_confidence is not None:
            try:
                weather_confidence = float(weather_confidence)
            except (TypeError, ValueError):
                weather_confidence = None
        weather_evidence = llm_parsed.get("weather_evidence")

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

        candidate_parsed_time = None
        if selected_candidate:
            candidate_parsed_time = (selected_candidate.get("parsed_time") or "").strip()
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

        # 事件/状态主要用于闹钟提醒。
        event_source = "none"
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
                event_source = (
                    "llm"
                    if candidate_event_conf >= EVENT_CONFIDENCE_THRESHOLD
                    else "llm_low_conf"
                )

        if event is None and llm_parsed.get("event"):
            sanitized = self._sanitize_event_text(llm_parsed.get("event") or "")
            if self._validate_event_text(sanitized):
                event = sanitized
                event_source = (
                    "llm"
                    if llm_event_confidence >= EVENT_CONFIDENCE_THRESHOLD
                    else "llm_low_conf"
                )

        if event is None and rule_result and rule_result.event:
            sanitized = self._sanitize_event_text(rule_result.event)
            if self._validate_event_text(sanitized):
                event = sanitized
                event_source = "rule"

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
            confidence = 0.6
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
        if is_health and intent_code not in ACTIONABLE_INTENTS and not safety_notice:
            safety_notice = DEFAULT_SAFETY_NOTICE

        if intent_code == IntentCode.UNKNOWN:
            if advice:
                need_clarify = True
                if not clarify_message:
                    clarify_message = "这些建议是否对您有帮助？需要我再安排其他服务吗？"
            else:
                need_clarify = True
                if not clarify_message:
                    clarify_message = "我暂时无法识别您的需求，可以再具体描述一下吗？"

        if (
            selected_candidate
            and selected_candidate.get("confidence", 0.0) < self._confidence_threshold
            and intent_code not in ACTIONABLE_INTENTS
        ):
            need_clarify = True
            if not clarify_message:
                clarify_message = "为了确认没有理解错，您可以再具体说明一下需求吗？"

        if intent_code in ACTIONABLE_INTENTS and confidence >= self._confidence_threshold:
            need_clarify = False
            clarify_message = None

        if result and result not in self._allowed_results:
            reasoning = (reasoning + "；" if reasoning else "") + "result 已校正为允许列表。"
            result = definition.result if intent_code != IntentCode.UNKNOWN else ""
            if not result:
                need_clarify = True
                if not clarify_message:
                    clarify_message = "我不是很确定您的需求，麻烦再具体描述一下好吗？"

        if need_clarify and not clarify_message:
            clarify_message = "我需要再确认一下，方便详细说明吗？"

        if intent_code in ACTIONABLE_INTENTS:
            advice = None
            safety_notice = None

        function_analysis = {
            "result": result,
            "target": target,
            "event": event,
            "status": status,
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
        }

        merge_meta = {
            "rule_promoted": rule_promoted,
            "llm_top_intent": llm_top_candidate_code.value if llm_top_candidate_code else None,
            "llm_top_result": llm_top_candidate_result,
            "event_source": event_source,
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
            conversation_state.last_selected_user = current_target
            return

        candidate_name = self._extract_candidate_name(query)
        if not candidate_name:
            return

        matched = None
        llm_match, llm_confidence = await self._match_candidate_with_llm(candidate_name, candidates)
        if llm_match and llm_match in candidates and llm_confidence >= 0.6:
            matched = llm_match
        if not matched:
            matched = self._fuzzy_match_candidate(candidate_name, candidates)
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
    def _extract_candidate_name(query: str) -> Optional[str]:
        cleaned = sanitize_person_name(query) or query.strip()
        if not cleaned:
            return None
        keywords = ["监测", "评估", "检测", "打开", "设置", "提醒", "帮我", "我要", "请", "联系"]
        if any(keyword in query for keyword in keywords) and len(cleaned) < len(query.strip()):
            return None
        return cleaned

    async def _match_candidate_with_llm(self, name: str, candidates: List[str]) -> tuple[Optional[str], float]:
        if not name or not candidates:
            return None, 0.0
        system_prompt = "你是中文人名匹配助手，只从候选列表中选择最接近的名字。"
        user_payload = {
            "candidates": candidates,
            "input": name,
            "output_format": {"match": "候选名单中的名字", "confidence": "0-1之间的小数"},
        }
        messages = [
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }
        ]
        try:
            raw, parsed = await self._llm_client.chat(
                system_prompt=system_prompt,
                messages=messages,
                response_format={"type": "json_object"},
            )
            _ = raw  # raw text暂时无需使用
        except Exception as exc:  # noqa: BLE001
            logger.debug("user candidate LLM match failed", error=str(exc))
            return None, 0.0

        match_name = parsed.get("match") if isinstance(parsed, dict) else None
        confidence = parsed.get("confidence") if isinstance(parsed, dict) else 0.0
        try:
            confidence_value = float(confidence) if confidence is not None else 0.0
        except (TypeError, ValueError):
            confidence_value = 0.0
        return match_name, confidence_value

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

    async def _ensure_alarm_details(
        self,
        query: str,
        function_analysis: Dict[str, Any],
    ) -> Optional[str]:
        if (function_analysis.get("result") or "").strip() != "新增闹钟":
            return None
        if not self._llm_client:
            return None

        existing_target = (function_analysis.get("target") or "").strip()
        previous_event = function_analysis.get("event")

        fallback_target, fallback_event, fallback_event_conf, fallback_reply = await self._parse_alarm_with_llm(query)
        if not fallback_target and not fallback_event:
            return fallback_reply

        if fallback_target and not existing_target:
            function_analysis["target"] = fallback_target

        if fallback_event:
            function_analysis["event"] = fallback_event
            marker = (
                "event_source=llm"
                if fallback_event_conf >= EVENT_CONFIDENCE_THRESHOLD
                else "event_source=llm_low_conf"
            )
        else:
            marker = None

        existing_confidence = function_analysis.get("confidence")
        try:
            numeric_conf = float(existing_confidence) if existing_confidence is not None else 0.0
        except (TypeError, ValueError):
            numeric_conf = 0.0
        function_analysis["confidence"] = max(numeric_conf, 0.75)

        reasoning_markers = ["alarm_details=llm"]
        if marker:
            reasoning_markers.append(marker)
        if previous_event and previous_event != function_analysis.get("event"):
            reasoning_markers.append("event_override=llm")
        reasoning = function_analysis.get("reasoning")
        addition = "；".join(reasoning_markers)
        function_analysis["reasoning"] = f"{reasoning}；{addition}" if reasoning else addition
        return fallback_reply

    async def _parse_alarm_with_llm(
        self,
        query: str,
    ) -> tuple[Optional[str], Optional[str], float, Optional[str]]:
        base_time = now_e8()
        payload = {
            "current_time": base_time.strftime("%Y-%m-%d %H:%M:%S%z"),
            "query": query,
            "instruction": (
                "请解析提醒/闹钟语句，输出 JSON："
                '{"target_iso":"2024-09-21 09:00:00","event":"买火车票","event_confidence":0.9,'
                '"status":"每周三","status_confidence":0.5,"confidence":0.92,'
                '"reply":"好的，我会在后天早上9点提醒您买火车票。"}。'
                "若无法确定，返回 {\"confidence\":0}。"
            ),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是时间解析助手，根据当前时间和用户指令，输出提醒的结构化信息。"
                    "必须仅返回 JSON，包含 target_iso、event、event_confidence、status、status_confidence、confidence、reply 字段。"
                    "若无法解析，请返回 {\"confidence\":0}。"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

        try:
            _, parsed = await self._llm_client.chat(
                system_prompt="",
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("alarm llm parse failed", error=str(exc))
            return None, None, 0.0, None

        if not isinstance(parsed, dict):
            return None, None, 0.0, None

        try:
            confidence = float(parsed.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.6:
            return None, None, 0.0, None

        target_iso = (parsed.get("target_iso") or parsed.get("target") or "").strip()
        if not target_iso:
            try:
                days = float(parsed.get("days", 0) or 0)
                hours = float(parsed.get("hours", 0) or 0)
                minutes = float(parsed.get("minutes", 0) or 0)
                seconds = float(parsed.get("seconds", 0) or 0)
            except (TypeError, ValueError):
                days = hours = minutes = seconds = 0.0
            delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            if timedelta(0) < delta < timedelta(days=365 * 5):
                reminder_time = (base_time + delta).astimezone(EAST_EIGHT)
                target_iso = reminder_time.strftime("%Y-%m-%d %H:%M:%S")

        if target_iso and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}[:\-]\d{2}[:\-]\d{2}$", target_iso):
            target_iso = target_iso.replace("-", ":", 2) if target_iso.count("-") > 2 else target_iso

        event_raw = (parsed.get("event") or "").strip()
        try:
            event_confidence = float(parsed.get("event_confidence", 0) or 0)
        except (TypeError, ValueError):
            event_confidence = 0.0
        sanitized_event = self._sanitize_event_text(event_raw)
        if not self._validate_event_text(sanitized_event):
            sanitized_event = None

        reply_hint = (parsed.get("reply") or "").strip() or None

        return target_iso or None, sanitized_event, event_confidence, reply_hint

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

    def _default_reply(self, function_analysis: Dict[str, Any]) -> str:
        """当大模型未返回 reply 字段时的兜底自然语言响应。"""
        result = function_analysis.get("result")
        advice = function_analysis.get("advice")
        safety = function_analysis.get("safety_notice")
        if function_analysis.get("need_clarify"):
            clarify = function_analysis.get("clarify_message") or "我需要确认一下您的需求，可以详细说明吗？"
            parts = [part for part in [advice, safety, clarify] if part]
            return " ".join(parts) if parts else clarify
        parts = [part for part in [advice, safety] if part]
        if result:
            parts.append(f"好的，我会为您处理{result}相关的请求。")
        if not parts:
            parts.append("好的，我在这里，随时为您服务。")
        return " ".join(parts).strip()

    def _is_health_related(self, query: str, advice: str | None, result: str | None) -> bool:
        """根据关键字快速判断当前语句是否属于健康相关场景。"""
        combined = (query or '') + (advice or '') + (result or '')
        return any(keyword in combined for keyword in HEALTH_KEYWORDS)
