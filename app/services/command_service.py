from __future__ import annotations

import json
from datetime import datetime, date, timedelta
from difflib import SequenceMatcher
from time import perf_counter
from typing import Iterable, Optional, Dict, Any, List

from cachetools import TTLCache

from loguru import logger

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse, FunctionAnalysis
from app.services.conversation import ConversationManager, ConversationState
from app.services.intent_classifier import IntentClassifier
from app.core.config import Settings
from app.services.llm_client import DoubaoClient
from app.services.weather_broadcast import WeatherBroadcastGenerator, WeatherBroadcastResult
from app.services.high_confidence_rules import HighConfidenceRuleEngine, RuleMatch
from app.services.weather_service import WeatherService
from app.services.prompt_templates import build_reply_prompt, build_user_selection_prompt
from app.utils.calendar_utils import format_lunar_summary, get_lunar_info
from app.utils.time_utils import describe_alarm_target, now_e8, sanitize_person_name, EAST_EIGHT


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

REQUIRES_SELECTION_RESULTS = HEALTH_MONITOR_RESULTS | {"健康评估", "健康画像", "小雅医生"}


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

    if result == "播报时间":
        try:
            current_time = now_e8().strftime("%Y-%m-%d %H:%M")
        except Exception:
            current_time = "当前时间"
        return f"现在是{current_time}，祝您行程安排顺利。"

    if result == "日期时间和万年历":
        target_iso = function_analysis.parsed_time or ""
        target_dt: Optional[datetime] = None
        if target_iso:
            try:
                target_dt = datetime.fromisoformat(target_iso)
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=EAST_EIGHT)
                else:
                    target_dt = target_dt.astimezone(EAST_EIGHT)
            except ValueError:
                target_dt = None
        if not target_dt:
            target_dt = now_e8()
        lunar = get_lunar_info(target_dt)
        summary = format_lunar_summary(lunar)
        label = (function_analysis.time_text or "当前日期").strip()
        date_text = target_dt.strftime("%Y年%m月%d日")
        if summary:
            return f"{label}（{date_text}）的农历信息：{summary}。"
        return f"{label}（{date_text}）暂无可用的农历详细信息，我会持续关注更新。"

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
        rule_engine: HighConfidenceRuleEngine | None = None,
        reply_llm_client: DoubaoClient | None = None,
    ) -> None:
        # 意图识别器：将用户输入转换为结构化 function_analysis。
        self._intent_classifier = intent_classifier
        # 会话管理器：维护多轮上下文、澄清状态等。
        self._conversation_manager = conversation_manager
        self._settings = settings
        self._weather_service = weather_service
        self._weather_broadcast_generator = weather_broadcast_generator
        self._rule_engine = rule_engine or HighConfidenceRuleEngine(settings.weather_default_city)
        self._reply_llm_client = reply_llm_client
        self._reply_prompt = build_reply_prompt() if reply_llm_client else None
        self._selection_prompt = build_user_selection_prompt() if reply_llm_client else None
        self._reply_cache: TTLCache | None = TTLCache(maxsize=256, ttl=60) if reply_llm_client else None
        self._selection_cache: TTLCache | None = TTLCache(maxsize=256, ttl=300) if reply_llm_client else None

    async def _handle_user_selection(
        self,
        *,
        session_id: str,
        query: str,
        meta_payload: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> Optional[CommandResponse]:
        last_analysis_dict = conversation_state.last_function_analysis or {}
        last_result = (last_analysis_dict.get("result") or "").strip()
        if not last_result or last_result not in REQUIRES_SELECTION_RESULTS:
            return None

        candidates = self._extract_user_candidates(meta_payload, conversation_state)
        if not candidates:
            return None

        name = sanitize_person_name(query) or query.strip()
        if not name:
            return None

        matched = self._match_candidate(name, candidates)
        if not matched:
            matched = await self._llm_select_candidate(
                query=name,
                candidates=candidates,
                session_id=session_id,
            )
        if not matched:
            return None

        analysis_model = FunctionAnalysis.model_validate(last_analysis_dict)
        analysis_model.target = matched
        analysis_model.confidence = max(analysis_model.confidence or 0.0, 0.92)
        analysis_model.need_clarify = False
        analysis_model.clarify_message = None
        if analysis_model.reasoning:
            analysis_model.reasoning += f"；目标用户匹配为{matched}"
        else:
            analysis_model.reasoning = f"目标用户匹配为{matched}"

        reply_message = _render_template(analysis_model) or _compose_response_message(
            analysis_model, ""
        )
        raw_output = ""
        function_analysis = analysis_model

        self._conversation_manager.update_state(
            session_id=session_id,
            query=query,
            response_message=reply_message,
            function_analysis=function_analysis,
            raw_llm_output=raw_output,
            user_candidates=candidates,
        )

        requires_selection = False
        response = CommandResponse(
            code=200,
            msg=reply_message,
            sessionId=session_id,
            requiresSelection=requires_selection,
            function_analysis=function_analysis,
        )
        logger.info(
            "user selection resolved",
            session_id=session_id,
            target=matched,
            candidates=candidates,
        )
        return response

    @staticmethod
    def _extract_user_candidates(
        meta_payload: Dict[str, Any],
        conversation_state: ConversationState,
    ) -> List[str]:
        raw = meta_payload.get("user_candidates")
        candidates: List[str] = []
        if isinstance(raw, str):
            candidates = [item.strip() for item in raw.split(",") if item.strip()]
        elif isinstance(raw, list):
            candidates = [str(item).strip() for item in raw if str(item).strip()]
        if not candidates:
            candidates = conversation_state.user_candidates
        if candidates and candidates != conversation_state.user_candidates:
            conversation_state.user_candidates = candidates
        return candidates

    def _match_candidate(self, name: str, candidates: List[str]) -> Optional[str]:
        if not name or not candidates:
            return None
        best_candidate = None
        best_score = 0.0
        for candidate in candidates:
            sanitized_candidate = sanitize_person_name(candidate) or candidate.strip()
            score = self._name_similarity(name, sanitized_candidate)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        if best_score >= 0.55:
            return best_candidate
        return None

    def _name_similarity(self, lhs: str, rhs: str) -> float:
        primary = SequenceMatcher(None, lhs, rhs).ratio()
        pinyin_ratio = 0.0
        lhs_py = self._to_pinyin(lhs)
        rhs_py = self._to_pinyin(rhs)
        if lhs_py and rhs_py:
            pinyin_ratio = SequenceMatcher(None, lhs_py, rhs_py).ratio()
        return max(primary, pinyin_ratio)

    @staticmethod
    def _to_pinyin(text: str) -> Optional[str]:
        try:
            from pypinyin import lazy_pinyin

            pinyin_tokens = lazy_pinyin(text)
            if not pinyin_tokens:
                return None
            return "".join(pinyin_tokens)
        except Exception:  # noqa: BLE001
            return None

    async def _llm_select_candidate(
        self,
        *,
        query: str,
        candidates: List[str],
        session_id: str,
    ) -> Optional[str]:
        if not self._reply_llm_client or not self._selection_prompt or not candidates:
            return None
        cache_key = None
        if self._selection_cache is not None:
            cache_key = (query, tuple(candidates))
            cached = self._selection_cache.get(cache_key)
            if cached:
                return cached

        payload = {
            "input": query,
            "candidates": candidates,
        }
        messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        try:
            raw_text, parsed = await self._reply_llm_client.chat(
                system_prompt=self._selection_prompt,
                messages=messages,
                response_format={"type": "json_object"},
                overrides={"max_tokens": 50, "temperature": 0.1, "top_p": 0.9},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("user selection LLM failed", error=str(exc), session_id=session_id)
            return None

        if isinstance(parsed, dict):
            candidate = parsed.get("match") or parsed.get("name") or parsed.get("target")
            if candidate and candidate in candidates:
                if cache_key and self._selection_cache is not None:
                    self._selection_cache[cache_key] = candidate
                return candidate
        logger.debug(
            "user selection llm parsed",
            session_id=session_id,
            query=query,
            raw_text=raw_text,
            parsed=parsed,
        )
        candidate = (raw_text or "").strip()
        if candidate in candidates:
            if cache_key and self._selection_cache is not None:
                self._selection_cache[cache_key] = candidate
            return candidate
        return None

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

    async def _generate_structured_reply(
        self,
        *,
        session_id: str,
        query: str,
        function_analysis: FunctionAnalysis,
        conversation_state: ConversationState,
        meta: Dict[str, Any],
    ) -> str:
        if not self._reply_llm_client or not self._reply_prompt:
            return ""
        history_messages = conversation_state.as_messages(limit=2)
        fa_dict = function_analysis.model_dump()
        cache_key = None
        if self._reply_cache is not None:
            cache_key = (
                query.strip(),
                json.dumps(fa_dict, ensure_ascii=False, sort_keys=True),
            )
            cached = self._reply_cache.get(cache_key)
            if cached:
                return cached

        payload = {
            "session_id": session_id,
            "query": query,
            "function_analysis": fa_dict,
        }
        if meta:
            payload["meta"] = meta
        user_message = json.dumps(payload, ensure_ascii=False)
        messages = [*history_messages, {"role": "user", "content": user_message}]
        try:
            raw_text, _ = await self._reply_llm_client.chat(
                system_prompt=self._reply_prompt,
                messages=messages,
                overrides={"max_tokens": 200, "temperature": 0.4, "top_p": 0.9},
            )
            reply_text = raw_text.strip()
            if cache_key and self._reply_cache is not None and reply_text:
                self._reply_cache[cache_key] = reply_text
            return reply_text
        except Exception as exc:  # noqa: BLE001
            logger.warning("short reply generation failed", error=str(exc), session_id=session_id)
            return ""

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

        selection_response = await self._handle_user_selection(
            session_id=session_id,
            query=payload.query,
            meta_payload=meta_payload,
            conversation_state=context,
        )
        if selection_response:
            return selection_response

        overall_start = perf_counter()
        rule_match: RuleMatch | None = None
        if self._rule_engine:
            rule_match = self._rule_engine.evaluate(payload.query, meta_payload)

        try:
            if rule_match:
                rule_source = "rule"
                function_analysis = rule_match.analysis
                reply_message = ""
                raw_output = ""
                weather_context = None
                weather_detail_payload = rule_match.weather_detail or {}
                weather_needs_realtime = rule_match.needs_realtime_weather
                if weather_detail_payload:
                    function_analysis.weather_detail = dict(weather_detail_payload)
            else:
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
                weather_context = None
                weather_detail_payload = function_analysis.weather_detail or {}
                weather_needs_realtime = getattr(function_analysis, "weather_needs_realtime", None)
                rule_source = "llm"

            if (
                self._weather_service
                and self._weather_service.enabled
                and weather_detail_payload
            ):
                weather_fetch_start = perf_counter()
                try:
                    weather_context = await self._weather_service.fetch(
                        llm_info=weather_detail_payload,
                        summary=function_analysis.weather_summary,
                        needs_realtime=bool(weather_needs_realtime),
                        query=payload.query,
                    )
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

            if weather_context:
                base_summary = weather_context.summary
                function_analysis.weather_summary = function_analysis.weather_summary or base_summary
                context_detail = weather_context.to_function_detail()
                merged_detail = {**weather_detail_payload, **context_detail}
                merged_detail.setdefault("needs_realtime_data", bool(weather_detail_payload.get("needs_realtime_data")))
                function_analysis.weather_detail = merged_detail
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

            if rule_match and not reply_message:
                reply_message = await self._generate_structured_reply(
                    session_id=session_id,
                    query=payload.query,
                    function_analysis=function_analysis,
                    conversation_state=context,
                    meta=meta_payload,
                )
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

        reply_origin = "rule" if rule_match else "llm"
        if use_fallback:
            fallback_candidate = trimmed_reply or (function_analysis.result or "")
            response_message = _compose_response_message(function_analysis, fallback_candidate)
            reply_source = reply_origin if rule_match else "fallback"
        else:
            response_message = trimmed_reply
            reply_source = reply_origin

        logger.debug(
            "classification_output",
            session_id=session_id,
            result=function_analysis.model_dump() if hasattr(function_analysis, "model_dump") else getattr(function_analysis, '__dict__', function_analysis),
            raw_llm_output=raw_output,
            reply_source=reply_source,
            rule_hit=bool(rule_match),
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
