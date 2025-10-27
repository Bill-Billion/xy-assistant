from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
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
        rule_result = run_rules(query, meta)
        logger.debug(
            "rule_result",
            session_id=session_id,
            rule_intent=getattr(rule_result, "intent_code", None),
            rule_target=getattr(rule_result, "target", None),
        )

        llm_response_text = ""
        llm_parsed: dict[str, Any] = {}
        try:
            messages = conversation_state.as_messages()
            reference_message = self._build_reference_message(query, rule_result, meta)
            if reference_message:
                messages.append({"role": "assistant", "content": reference_message})
            messages.append({"role": "user", "content": query})
            llm_response_text, llm_parsed = await self._llm_client.chat(
                system_prompt=self._system_prompt,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM 调用失败，采用规则兜底", error=str(exc))

        function_analysis, intent_code = self._merge_results(rule_result, llm_parsed, query)
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
        await self._ensure_alarm_target(
            query=query,
            function_analysis=function_analysis,
        )
        await self._ensure_alarm_target(
            query=query,
            function_analysis=function_analysis,
        )

        reply_message = (
            llm_parsed.get("reply")
            or function_analysis.get("clarify_message")
            or self._default_reply(function_analysis)
        )

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

        logger.info(
            "classification completed",
            session_id=session_id,
            function_analysis=function_analysis,
            llm_parsed=llm_parsed,
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
        if meta:
            hints.append(f"- 上下文信息：{json.dumps(meta, ensure_ascii=False)}")
        content = "\n".join(hints)
        return content if len(hints) > 1 else None

    def _merge_results(
        self,
        rule_result: Optional[RuleResult],
        llm_parsed: Dict[str, Any],
        query: str,
    ) -> tuple[Dict[str, Any], IntentCode]:
        """合并规则结果与大模型 JSON，并执行后置校验与补全。"""
        llm_parsed = llm_parsed or {}
        raw_result = llm_parsed.get("result")

        intent_code = self._resolve_intent_code(rule_result, llm_parsed)
        definition = INTENT_DEFINITIONS.get(intent_code, INTENT_DEFINITIONS[IntentCode.UNKNOWN])

        # 结果优先级：规则细分 > LLM 合法枚举 > 枚举默认值 > 原始 LLM 结果
        llm_result = llm_parsed.get("result")
        if rule_result and rule_result.result:
            result = rule_result.result
        elif llm_result and llm_result in self._allowed_results:
            result = llm_result
        elif intent_code != IntentCode.UNKNOWN:
            result = definition.result
        else:
            result = llm_result or ""

        target = llm_parsed.get("target") or ""
        if isinstance(target, str):
            target = target.strip()
        if (not target) and rule_result and rule_result.target is not None:
            target = rule_result.target

        # 事件/状态主要用于闹钟提醒。
        event = llm_parsed.get("event")
        status = llm_parsed.get("status")
        if event is None and rule_result:
            event = rule_result.event
        if status is None and rule_result:
            status = rule_result.status

        confidence = llm_parsed.get("confidence")
        if confidence is None and rule_result and rule_result.confidence is not None:
            confidence = rule_result.confidence
        if confidence is None:
            confidence = 0.6
        if rule_result:
            # 如果规则提供置信度，则与 LLM 结果取较高值，确保明确意图不被降权。
            rule_conf = rule_result.confidence if rule_result.confidence is not None else 0.95
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(confidence, rule_conf)
        confidence = min(max(float(confidence), 0.0), 1.0)

        need_clarify = bool(llm_parsed.get("need_clarify", False))
        clarify_message = llm_parsed.get("clarify_message") or None
        if rule_result and rule_result.need_clarify:
            need_clarify = True
        if rule_result and rule_result.clarify_message and not clarify_message:
            clarify_message = rule_result.clarify_message

        reasoning_parts: list[str] = []
        if llm_parsed.get("reasoning"):
            reasoning_parts.append(str(llm_parsed["reasoning"]))
        if rule_result and rule_result.reasoning:
            reasoning_parts.append(rule_result.reasoning)
        if raw_result and raw_result != result:
            reasoning_parts.append(f"LLM_suggested_result={raw_result}")
        advice = (llm_parsed.get("advice") or "").strip()
        safety_notice = (llm_parsed.get("safety_notice") or "").strip()

        reasoning = "；".join(reasoning_parts) or None

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
        }

        return function_analysis, intent_code

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

    async def _ensure_alarm_target(
        self,
        query: str,
        function_analysis: Dict[str, Any],
    ) -> None:
        if (function_analysis.get("result") or "").strip() != "新增闹钟":
            return
        if (function_analysis.get("target") or "").strip():
            return
        if not self._llm_client:
            return

        fallback_target, fallback_event = await self._parse_alarm_with_llm(query)
        if not fallback_target:
            return

        function_analysis["target"] = fallback_target
        if fallback_event and not function_analysis.get("event"):
            function_analysis["event"] = fallback_event

        existing_confidence = function_analysis.get("confidence")
        try:
            numeric_conf = float(existing_confidence) if existing_confidence is not None else 0.0
        except (TypeError, ValueError):
            numeric_conf = 0.0
        function_analysis["confidence"] = max(numeric_conf, 0.75)

        marker = "alarm_target=llm"
        reasoning = function_analysis.get("reasoning")
        function_analysis["reasoning"] = f"{reasoning}；{marker}" if reasoning else marker

    async def _parse_alarm_with_llm(self, query: str) -> tuple[Optional[str], Optional[str]]:
        base_time = now_e8()
        payload = {
            "current_time": base_time.strftime("%Y-%m-%d %H:%M:%S%z"),
            "query": query,
            "instruction": (
                "解析提醒中的相对时间，返回 JSON："
                '{"days":0,"hours":0,"minutes":10,"seconds":0,"event":"事件","confidence":0.9}。'
                "若无法确定，返回 {\"confidence\":0}。"
            ),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是时间解析助手，根据当前时间和用户指令，输出提醒的时间间隔（天/小时/分钟/秒）"
                    "并提炼提醒事项 event，只能输出 JSON。"
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
            return None, None

        if not isinstance(parsed, dict):
            return None, None

        try:
            confidence = float(parsed.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.6:
            return None, None

        try:
            days = float(parsed.get("days", 0) or 0)
            hours = float(parsed.get("hours", 0) or 0)
            minutes = float(parsed.get("minutes", 0) or 0)
            seconds = float(parsed.get("seconds", 0) or 0)
        except (TypeError, ValueError):
            return None, None

        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta <= timedelta(0) or delta > timedelta(days=365 * 5):
            return None, None

        reminder_time = (base_time + delta).astimezone(EAST_EIGHT)
        target = reminder_time.strftime("%Y-%m-%d %H-%M-%S")
        event = (parsed.get("event") or "").strip() or None
        return target, event

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
