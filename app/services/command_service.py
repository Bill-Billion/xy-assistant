from __future__ import annotations

from datetime import datetime, date, timedelta
from time import perf_counter
from typing import Iterable, Optional

from loguru import logger

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse, FunctionAnalysis
from app.services.conversation import ConversationManager
from app.services.intent_classifier import IntentClassifier
from app.core.config import Settings
from app.services.weather_broadcast import WeatherBroadcastGenerator, WeatherBroadcastResult
from app.services.weather_service import WeatherService
from app.utils.time_utils import describe_alarm_target, now_e8


HEALTH_MONITOR_RESULTS = {
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
}

REQUIRES_SELECTION_RESULTS = HEALTH_MONITOR_RESULTS | {"健康评估", "健康画像"}


_WEATHER_CONDITION_TEXT = {
    "sunny": "晴天",
    "rain": "下雨",
    "snow": "下雪",
    "wind": "风大",
    "hot": "炎热",
    "cold": "寒冷",
    "air_quality": "空气质量",
    "temperature": "气温",
    "rain_chance": "降雨概率",
}


def _format_target_phrase(target_date: Optional[str]) -> str:
    if not target_date:
        return "今天"
    try:
        date_obj = datetime.fromisoformat(target_date).date()
    except ValueError:
        return target_date
    today = now_e8().date()
    if date_obj == today:
        return "今天"
    if date_obj == today + timedelta(days=1):
        return "明天"
    if date_obj == today + timedelta(days=2):
        return "后天"
    return date_obj.strftime("%m月%d日")


def _evaluate_weather_condition(
    condition: Optional[str],
    context: "WeatherContext",
) -> tuple[Optional[str], list[str]]:
    if not condition:
        return None, []

    derived = context.derived_flags or {}
    target = derived.get("target_day", {})
    current = derived.get("current", {})
    evidence: list[str] = []
    judgement: Optional[str] = None

    target_phrase = _format_target_phrase(derived.get("target_date"))
    location = derived.get("location") or context.location

    day_text = target.get("day_text")
    night_text = target.get("night_text")
    if day_text or night_text:
        text_parts = [part for part in [day_text, night_text] if part]
        evidence.append(f"{location}{target_phrase}{'、'.join(text_parts)}")

    precip_probability = target.get("precip_probability")
    if precip_probability is not None:
        evidence.append(f"预报降水概率 {int(round(precip_probability * 100))}%")

    high = target.get("high_temp")
    low = target.get("low_temp")
    if high is not None or low is not None:
        if high is not None and low is not None:
            evidence.append(f"气温范围 {low}~{high}℃")
        elif high is not None:
            evidence.append(f"最高温 {high}℃")
        elif low is not None:
            evidence.append(f"最低温 {low}℃")

    if condition == "sunny":
        if target.get("is_sunny"):
            judgement = "yes"
        elif target.get("has_rain") or target.get("has_snow"):
            judgement = "no"
    elif condition == "rain":
        if target.get("has_rain") or (precip_probability is not None and precip_probability >= 0.4):
            judgement = "yes"
        elif target.get("has_snow"):
            judgement = "no"
        elif precip_probability is not None and precip_probability <= 0.2:
            judgement = "no"
    elif condition == "snow":
        if target.get("has_snow"):
            judgement = "yes"
        elif target.get("has_rain") or target.get("is_sunny"):
            judgement = "no"
    elif condition == "hot":
        if target.get("is_hot"):
            judgement = "yes"
        elif high is not None and high <= 28:
            judgement = "no"
    elif condition == "cold":
        if target.get("is_cold"):
            judgement = "yes"
        elif low is not None and low >= 8:
            judgement = "no"
    elif condition == "air_quality":
        quality = current.get("aqi")
        if quality:
            evidence.append(f"空气质量 {quality}")
    elif condition == "temperature":
        # 已在证据中包含高低温
        pass
    elif condition == "wind":
        wind = target.get("wind") or current.get("wind_power")
        if wind:
            evidence.append(f"风力 {wind}")
    elif condition == "rain_chance":
        if precip_probability is not None:
            if precip_probability >= 0.6:
                judgement = "yes"
            elif precip_probability <= 0.3:
                judgement = "no"

    return judgement, evidence
def _render_template(function_analysis: FunctionAnalysis) -> str | None:
    """根据结果字段选择固定回复模板。返回 (模板文本, 可能的枚举意图)."""
    result = function_analysis.result or ""

    if result == "新增闹钟":
        readable_target = describe_alarm_target(function_analysis.target or "", now_e8())
        message = f"好的，我已为您设置{readable_target}的闹钟。"
        if function_analysis.event:
            message += f" 提醒事项：{function_analysis.event}。"
        if function_analysis.status:
            message += f" 频次：{function_analysis.status}。"
        return message.strip()

    if result == "关闭音乐":
        return "好的，正在关闭音乐。"

    if result == "关闭听书":
        return "好的，正在关闭听书。"

    if result == "关闭戏曲":
        return "好的，正在关闭戏曲。"

    if "天气" in result and getattr(function_analysis, "weather_summary", None):
        summary = function_analysis.weather_summary
        condition = getattr(function_analysis, "weather_condition", None)
        judgement = getattr(function_analysis, "weather_judgement", None)
        detail = getattr(function_analysis, "weather_detail", {}) or {}
        evidence = getattr(function_analysis, "weather_evidence", None) or []
        target_phrase = _format_target_phrase(detail.get("target_date"))
        location = detail.get("location") or ""
        if condition and judgement:
            condition_text = _WEATHER_CONDITION_TEXT.get(condition, condition)
            verdict = "是" if judgement == "yes" else "不是"
            location_phrase = f"{location}{target_phrase}" if location else target_phrase
            message_parts = [summary]
            message_parts.append(f"根据以上数据判断，{location_phrase}{verdict}{condition_text}。")
            if evidence:
                message_parts.append("参考依据：" + "；".join(evidence) + "。")
            return " ".join(part for part in message_parts if part).strip()
        return summary

    if result in HEALTH_MONITOR_RESULTS:
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开{result}功能。"
        return f"好的，我已为您打开{result}功能。"

    if result == "息屏":
        return "好的，正在为您息屏。"

    return None


def _compose_response_message(function_analysis: FunctionAnalysis, fallback: str) -> str:
    """
    根据分析结果动态拼接返回给前端的 msg。
    可执行意图优先使用模板，咨询类按“建议→安全提示→澄清”组合。
    """
    parts: list[str] = []

    def add_unique(text: str | None) -> None:
        candidate = (text or "").strip()
        if not candidate:
            return
        for existing in parts:
            if candidate in existing or existing in candidate:
                return
        parts.append(candidate)

    template_text = _render_template(function_analysis)
    advice = (function_analysis.advice or "").strip()
    safety = (function_analysis.safety_notice or "").strip()
    clarify = (function_analysis.clarify_message or "").strip()
    fallback_text = fallback.strip()

    if function_analysis.need_clarify and clarify:
        add_unique(template_text)
        add_unique(advice)
        add_unique(safety)
        add_unique(clarify)
        if not parts:
            add_unique(fallback_text)
        return " ".join(parts)

    if template_text:
        add_unique(template_text)
        add_unique(advice)
        add_unique(safety)
    else:
        add_unique(fallback_text)
        add_unique(advice)
        add_unique(safety)

    if not parts:
        add_unique(fallback_text or fallback)

    return " ".join(parts)


class CommandService:
    """命令服务门面，负责协调意图识别与会话状态更新。"""

    def __init__(
        self,
        intent_classifier: IntentClassifier,
        conversation_manager: ConversationManager,
        settings: Settings,
        weather_service: WeatherService | None = None,
        weather_broadcast_generator: WeatherBroadcastGenerator | None = None,
    ) -> None:
        # 意图识别器：将用户输入转换为结构化 function_analysis。
        self._intent_classifier = intent_classifier
        # 会话管理器：维护多轮上下文、澄清状态等。
        self._conversation_manager = conversation_manager
        self._settings = settings
        self._weather_service = weather_service
        self._weather_broadcast_generator = weather_broadcast_generator

    async def _generate_weather_broadcast(
        self,
        weather_context: "WeatherContext",
        analysis: FunctionAnalysis,
        user_query: str,
    ) -> WeatherBroadcastResult:
        if not self._weather_broadcast_generator or not self._weather_broadcast_generator.enabled():
            return WeatherBroadcastResult(None, 0.0, {})
        return await self._weather_broadcast_generator.generate(
            weather_context=weather_context,
            analysis=analysis,
            user_query=user_query,
        )

    async def handle_command(self, payload: CommandRequest) -> CommandResponse:
        session_id = payload.session_id or self._conversation_manager.generate_session_id()
        # 提取会话上下文，便于构造多轮提示词。
        context = self._conversation_manager.get_state(session_id)

        candidate_users: list[str] = []
        if payload.user:
            candidate_users = [
                name.strip()
                for name in payload.user.split(",")
                if isinstance(name, str) and name.strip()
            ]
            if candidate_users:
                context.user_candidates = candidate_users
                self._conversation_manager.set_user_candidates(session_id, candidate_users)

        # 组装 meta 信息，同时注入候选联系人，便于后续意图解析精准匹配。
        meta_payload = dict(payload.meta or {})
        if candidate_users:
            meta_payload["user_candidates"] = candidate_users
        elif context.user_candidates:
            meta_payload["user_candidates"] = context.user_candidates

        logger.info(
            "handling command",
            session_id=session_id,
            query=payload.query,
            meta=payload.meta,
        )

        overall_start = perf_counter()
        weather_context = None
        # 天气相关问题提前调用天气服务，供模型作为结构化上下文使用。
        if (
            self._weather_service
            and self._weather_service.enabled
            and payload.query
            and "天气" in payload.query
        ):
            weather_fetch_start = perf_counter()
            try:
                weather_context = await self._weather_service.fetch(payload.query)
                if weather_context:
                    meta_payload["weather"] = weather_context.to_prompt_dict()
            except Exception as exc:  # noqa: BLE001
                logger.warning("weather context fetch failed", error=str(exc))
                weather_context = None
            else:
                logger.debug(
                    "timing handle_command",
                    step="weather_fetch",
                    duration=round(perf_counter() - weather_fetch_start, 3),
                    session_id=session_id,
                )

        try:
            classify_start = perf_counter()
            # 核心步骤：调用意图分类器，结合大模型与规则得到结构化分析。
            classification = await self._intent_classifier.classify(
                session_id=session_id,
                query=payload.query,
                meta=meta_payload,
                conversation_state=context,
            )
            logger.debug(
                "timing handle_command",
                step="intent_classifier",
                duration=round(perf_counter() - classify_start, 3),
                session_id=session_id,
            )
            # 将原始结果转为响应模型，确保字段类型一致。
            function_analysis = FunctionAnalysis.model_validate(classification.function_analysis)
            reply_message = classification.reply_message
            raw_output = classification.raw_llm_output
            if weather_context and function_analysis.result and "天气" in (function_analysis.result or ""):
                base_summary = weather_context.summary
                function_analysis.weather_summary = function_analysis.weather_summary or base_summary
                function_analysis.weather_detail = weather_context.to_function_detail()
                meta_payload["weather"] = weather_context.to_prompt_dict()
                broadcast_start = perf_counter()
                broadcast_result = await self._generate_weather_broadcast(
                    weather_context=weather_context,
                    analysis=function_analysis,
                    user_query=payload.query,
                )
                logger.debug(
                    "timing handle_command",
                    step="weather_broadcast",
                    duration=round(perf_counter() - broadcast_start, 3),
                    session_id=session_id,
                )
                if broadcast_result.metadata:
                    weather_context.llm_metadata.setdefault("broadcast", broadcast_result.metadata)
                if broadcast_result.message:
                    function_analysis.weather_summary = broadcast_result.message
                    existing_conf = function_analysis.weather_confidence or 0.0
                    function_analysis.weather_confidence = max(
                        existing_conf,
                        max(0.0, min(broadcast_result.confidence, 1.0)),
                    )
                else:
                    function_analysis.weather_summary = function_analysis.weather_summary or base_summary
                function_analysis.weather_detail = weather_context.to_function_detail()
                meta_payload["weather"] = weather_context.to_prompt_dict()
                judgement, evidence = _evaluate_weather_condition(
                    getattr(function_analysis, "weather_condition", None),
                    weather_context,
                )
                if evidence:
                    function_analysis.weather_evidence = evidence
                if judgement:
                    function_analysis.weather_judgement = judgement
                    try:
                        current_conf = float(function_analysis.weather_confidence or 0)
                    except (TypeError, ValueError):
                        current_conf = 0.0
                    if current_conf < 0.9:
                        function_analysis.weather_confidence = 0.9
                if not function_analysis.reasoning:
                    reasoning_notes = [f"引用实时天气：{weather_context.summary}"]
                    if judgement:
                        verdict = "成立" if judgement == "yes" else "不成立"
                        condition_text = _WEATHER_CONDITION_TEXT.get(function_analysis.weather_condition or "", "天气情况")
                        reasoning_notes.append(f"条件判断结果：{condition_text}{verdict}")
                    if evidence:
                        reasoning_notes.append("依据：" + "；".join(evidence))
                    function_analysis.reasoning = "；".join(reasoning_notes)
                detail_meta = function_analysis.weather_detail or {}
                source_notes: list[str] = []
                loc_source = detail_meta.get("location_source")
                if loc_source == "default":
                    source_notes.append("未识别具体地名，使用默认城市。")
                elif loc_source == "llm":
                    source_notes.append("地名来源于模型解析。")
                elif loc_source == "llm_low":
                    source_notes.append("地名为模型推测结果，请留意是否准确。")
                date_source = detail_meta.get("target_date_source")
                if date_source == "llm":
                    source_notes.append("日期参考模型解析。")
                elif date_source == "default" and not weather_context.target_date:
                    source_notes.append("未解析到具体日期。")
                if source_notes:
                    if function_analysis.reasoning:
                        function_analysis.reasoning += "；" + "；".join(source_notes)
                    else:
                        function_analysis.reasoning = "；".join(source_notes)
        except Exception as exc:  # noqa: BLE001
            logger.exception("classification failed, using fallback", error=str(exc))
            function_analysis = FunctionAnalysis(
                result="未知指令",
                target="",
                event=None,
                status=None,
                confidence=0.0,
                need_clarify=True,
                clarify_message="我暂时无法理解您的需求，可以换种说法吗？",
                reasoning="遭遇异常，使用兜底策略",
            )
            reply_message = function_analysis.clarify_message or "请再描述一次您的需求。"
            raw_output = ""
            if weather_context and "天气" in (function_analysis.result or ""):
                function_analysis.weather_summary = weather_context.summary
                function_analysis.weather_detail = weather_context.to_function_detail()
                judgement, evidence = _evaluate_weather_condition(
                    getattr(function_analysis, "weather_condition", None),
                    weather_context,
                )
                if evidence:
                    function_analysis.weather_evidence = evidence
                if judgement:
                    function_analysis.weather_judgement = judgement
                    function_analysis.weather_confidence = 0.9
                detail_meta = function_analysis.weather_detail or {}
                source_notes: list[str] = []
                loc_source = detail_meta.get("location_source")
                if loc_source == "default":
                    source_notes.append("未识别具体地名，使用默认城市。")
                elif loc_source == "llm":
                    source_notes.append("地名来源于模型解析。")
                elif loc_source == "llm_low":
                    source_notes.append("地名为模型推测结果，请留意是否准确。")
                date_source = detail_meta.get("target_date_source")
                if date_source == "llm":
                    source_notes.append("日期参考模型解析。")
                elif date_source == "default" and not weather_context.target_date:
                    source_notes.append("未解析到具体日期。")
                if source_notes:
                    if function_analysis.reasoning:
                        function_analysis.reasoning += "；" + "；".join(source_notes)
                    else:
                        function_analysis.reasoning = "；".join(source_notes)

        trimmed_reply = (reply_message or "").strip()
        use_fallback = False
        if not trimmed_reply:
            use_fallback = True
        elif function_analysis.need_clarify and not function_analysis.clarify_message:
            use_fallback = True

        if use_fallback:
            response_message = _compose_response_message(function_analysis, trimmed_reply)
            reply_source = "fallback"
        else:
            response_message = trimmed_reply
            reply_source = "llm"

        logger.debug(
            "classification_output",
            session_id=session_id,
            result=function_analysis.model_dump() if hasattr(function_analysis, "model_dump") else getattr(function_analysis, '__dict__', function_analysis),
            raw_llm_output=raw_output,
            reply_source=reply_source,
        )
        logger.debug(
            "timing handle_command",
            step="total",
            duration=round(perf_counter() - overall_start, 3),
            session_id=session_id,
        )

        self._conversation_manager.update_state(
            session_id=session_id,
            query=payload.query,
            response_message=response_message,
            function_analysis=function_analysis,
            raw_llm_output=raw_output,
            user_candidates=context.user_candidates,
        )

        fa_result = (function_analysis.result or "").strip()
        fa_target = (function_analysis.target or "").strip()
        requires_selection = bool(function_analysis.need_clarify) or (
            fa_result in REQUIRES_SELECTION_RESULTS and not fa_target
        )

        return CommandResponse(
            code=200,
            msg=response_message,
            sessionId=session_id,
            requires_selection=requires_selection,
            function_analysis=function_analysis,
        )
