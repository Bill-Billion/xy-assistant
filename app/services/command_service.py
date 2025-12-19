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
from app.services.prompt_templates import (
    build_reply_prompt,
    build_user_selection_prompt,
    build_weather_reply_prompt,
    build_city_extraction_prompt,
    build_lunar_strategy_prompt,
)
from app.utils.calendar_utils import format_lunar_summary, get_lunar_info
from app.utils.time_utils import (
    EAST_EIGHT,
    describe_alarm_target,
    extract_lunar_date_spec,
    get_current_lunar_year,
    now_e8,
    resolve_lunar_to_solar,
    sanitize_person_name,
)
from app.utils.location_utils import extract_city_from_query, normalize_city_name


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

REQUIRES_SELECTION_RESULTS = HEALTH_MONITOR_RESULTS | {"健康评估", "健康画像", "小雅医生", "家庭医生"}


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

_NUMERAL_TOKENS = {
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
    "零",
    "〇",
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
        # 若用户询问的是“农历X月X是什么时候”，优先播报其对应公历日期
        if "农历" in label:
            return f"{label}对应的公历日期是{date_text}。"
        if summary:
            return f"{label}（{date_text}）的农历信息：{summary}。"
        return f"{label}（{date_text}）暂无可用的农历详细信息，我会持续关注更新。"

    if result == "笑话模式":
        return "好的，我给您讲个轻松的小笑话。"

    if result == "继续播放":
        target_label = function_analysis.target or ""
        if target_label:
            return f"好的，现在为您继续播放{target_label}。"
        return "好的，现在继续为您播放。"

    if result in HEALTH_MONITOR_RESULTS:
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开{result}功能。"
        return f"好的，我已为您打开{result}功能。"

    if result in {"健康画像", "健康评估"}:
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开{result}功能。"
        return f"好的，我已为您打开{result}功能。"

    if result == "家庭医生":
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开家庭医生服务。"
        return "好的，我已为您打开家庭医生服务。"

    if result == "小雅医生":
        if function_analysis.target:
            return f"好的，我已为{function_analysis.target}打开小雅医生功能。"
        return "好的，我已为您打开小雅医生功能。"

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
        self._weather_reply_prompt = build_weather_reply_prompt() if reply_llm_client else None
        self._city_extraction_prompt = build_city_extraction_prompt() if reply_llm_client else None
        self._lunar_strategy_prompt = build_lunar_strategy_prompt() if reply_llm_client else None
        self._reply_cache: TTLCache | None = TTLCache(maxsize=256, ttl=60) if reply_llm_client else None
        self._selection_cache: TTLCache | None = TTLCache(maxsize=256, ttl=300) if reply_llm_client else None
        self._city_cache: TTLCache | None = TTLCache(maxsize=256, ttl=300) if reply_llm_client else None
        self._lunar_strategy_cache: TTLCache | None = TTLCache(maxsize=256, ttl=600) if reply_llm_client else None
        self._local_weather_cache: TTLCache | None = (
            TTLCache(maxsize=32, ttl=180) if weather_service and weather_service.enabled else None
        )

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

    async def _generate_weather_reply_text(
        self,
        *,
        query: str,
        summary: str,
        detail: dict[str, Any] | None,
    ) -> str:
        if not self._reply_llm_client or not self._weather_reply_prompt:
            return summary
        prompt_payload = {
            "query": query,
            "summary": summary,
            "detail": detail or {},
        }
        user_message = json.dumps(prompt_payload, ensure_ascii=False)
        try:
            raw_text, _ = await self._reply_llm_client.chat(
                system_prompt=self._weather_reply_prompt,
                messages=[{"role": "user", "content": user_message}],
                overrides={"max_tokens": 160, "temperature": 0.4, "top_p": 0.8},
            )
            candidate = raw_text.strip()
            return candidate or summary
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather reply generation failed", error=str(exc))
            return summary

    async def _llm_extract_city(self, payload: Dict[str, Any]) -> Optional[str]:
        if not self._reply_llm_client or not self._city_extraction_prompt:
            return None
        cache_key = None
        if self._city_cache is not None:
            try:
                cache_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                cache_key = None
            else:
                cached = self._city_cache.get(cache_key)
                if cached is not None:
                    return cached or None
        try:
            raw_text, parsed = await self._reply_llm_client.chat(
                system_prompt=self._city_extraction_prompt,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                response_format={"type": "json_object"},
                overrides={"max_tokens": 80, "temperature": 0},
            )
            if isinstance(parsed, dict):
                city = (parsed.get("city") or "").strip()
                confidence = parsed.get("confidence")
                try:
                    confidence_value = float(confidence) if confidence is not None else 0.0
                except (TypeError, ValueError):
                    confidence_value = 0.0
                if city and confidence_value >= 0.4:
                    if cache_key and self._city_cache is not None:
                        self._city_cache[cache_key] = city
                    return city
            if cache_key and self._city_cache is not None:
                self._city_cache[cache_key] = ""
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("city extraction LLM failed", error=str(exc))
            return None

    async def _llm_decide_lunar_strategy(
        self,
        *,
        session_id: str,
        query: str,
        lunar_phrase: str,
        current_lunar_year: int,
    ) -> Dict[str, Any]:
        """
        使用 LLM 判断农历查询策略（未来最近一次 / 今年 / 需要澄清 / 年份偏移）。
        仅用于“农历X月X”这类需要转换为公历的场景，提示词尽量短以控制时延。
        """
        default_decision: Dict[str, Any] = {
            "strategy": "next_occurrence",
            "year_offset": None,
            "need_clarify": False,
            "clarify_message": "",
        }
        if not self._reply_llm_client or not self._lunar_strategy_prompt:
            return default_decision

        payload = {
            "query": (query or "").strip(),
            "lunar_phrase": lunar_phrase,
            "base_time_e8": now_e8().strftime("%Y-%m-%d %H:%M:%S"),
            "current_lunar_year": current_lunar_year,
        }

        cache_key = None
        if self._lunar_strategy_cache is not None:
            try:
                cache_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                cache_key = None
            else:
                cached = self._lunar_strategy_cache.get(cache_key)
                if isinstance(cached, dict):
                    return dict(default_decision, **cached)

        try:
            _raw, parsed = await self._reply_llm_client.chat(
                system_prompt=self._lunar_strategy_prompt,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                response_format={"type": "json_object"},
                overrides={"max_tokens": 120, "temperature": 0.2, "top_p": 0.9},
            )
            if not isinstance(parsed, dict):
                return default_decision

            strategy = (parsed.get("strategy") or "").strip()
            if strategy not in {"next_occurrence", "this_year", "year_offset", "ask_clarify"}:
                strategy = "next_occurrence"

            year_offset = parsed.get("year_offset")
            year_offset_value: Optional[int] = None
            if strategy == "year_offset":
                try:
                    year_offset_value = int(year_offset)
                except (TypeError, ValueError):
                    year_offset_value = None

            need_clarify = bool(parsed.get("need_clarify", False))
            clarify_message = (parsed.get("clarify_message") or "").strip()
            if strategy == "ask_clarify":
                need_clarify = True

            decision = {
                "strategy": strategy,
                "year_offset": year_offset_value,
                "need_clarify": need_clarify,
                "clarify_message": clarify_message,
            }
            if cache_key and self._lunar_strategy_cache is not None:
                self._lunar_strategy_cache[cache_key] = decision
            return dict(default_decision, **decision)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lunar strategy LLM failed", error=str(exc), session_id=session_id)
            return default_decision

    async def _maybe_resolve_lunar_calendar(
        self,
        *,
        session_id: str,
        query: str,
        function_analysis: FunctionAnalysis,
    ) -> Optional[str]:
        """
        对“农历X月X是什么时候”这类询问：
        - 先用 LLM 判定策略（未来最近一次/今年/需澄清）
        - 再用 lunar_python 做确定性转换，写入 target/parsed_time/time_text
        - 返回用于 msg 的文本（优先使用模板），若无需处理则返回 None
        """
        if (function_analysis.result or "").strip() != "日期时间和万年历":
            return None

        spec = extract_lunar_date_spec(query)
        if not spec:
            return None

        base_time = now_e8()
        current_lunar_year = get_current_lunar_year(base_time)
        decision = await self._llm_decide_lunar_strategy(
            session_id=session_id,
            query=query,
            lunar_phrase=spec.phrase,
            current_lunar_year=current_lunar_year,
        )

        if decision.get("need_clarify") and decision.get("clarify_message"):
            function_analysis.need_clarify = True
            function_analysis.clarify_message = decision.get("clarify_message") or None
            function_analysis.target = ""
            if function_analysis.reasoning:
                function_analysis.reasoning += "；lunar_strategy=ask"
            else:
                function_analysis.reasoning = "lunar_strategy=ask"
            return function_analysis.clarify_message or ""

        strategy = decision.get("strategy") or "next_occurrence"
        year_offset = decision.get("year_offset")
        dt = resolve_lunar_to_solar(
            spec,
            base_time=base_time,
            strategy=strategy,
            year_offset=year_offset,
            max_years=15,
        )
        if dt is None and strategy != "next_occurrence":
            dt = resolve_lunar_to_solar(spec, base_time=base_time, strategy="next_occurrence", max_years=20)
        if dt is None:
            # 极端情况：无法转换（可能是非法日期），交给澄清
            function_analysis.need_clarify = True
            function_analysis.clarify_message = "我需要确认您要查询的农历日期是否正确（例如是否为闰月/日期是否存在），方便再说一下吗？"
            function_analysis.target = ""
            if function_analysis.reasoning:
                function_analysis.reasoning += "；lunar_convert_failed"
            else:
                function_analysis.reasoning = "lunar_convert_failed"
            return function_analysis.clarify_message

        function_analysis.time_text = spec.phrase
        function_analysis.parsed_time = dt.isoformat()
        function_analysis.target = dt.strftime("%Y-%m-%d %H:%M:%S")
        function_analysis.time_confidence = max(function_analysis.time_confidence or 0.0, 0.99)
        function_analysis.time_source = "lunar_python"
        function_analysis.need_clarify = False
        function_analysis.clarify_message = None
        if function_analysis.reasoning:
            function_analysis.reasoning += f"；lunar_strategy={strategy}"
        else:
            function_analysis.reasoning = f"lunar_strategy={strategy}"
        date_text = dt.strftime("%Y年%m月%d日")
        return f"{spec.phrase}对应的公历日期是{date_text}。"

    def _resolve_context_city(self, meta_payload: Dict[str, Any]) -> str:
        """提取用于天气查询的城市信息，默认回退到系统配置。"""
        default_city = self._settings.weather_default_city
        if not meta_payload:
            return default_city
        # 优先使用显式 city 字段
        city_field = meta_payload.get("city")
        if isinstance(city_field, str) and city_field.strip():
            normalized, _ = normalize_city_name(city_field.strip(), default_city)
            if normalized:
                return normalized
        if isinstance(city_field, dict):
            for key in ("city", "name", "display", "text"):
                value = city_field.get(key)
                if isinstance(value, str) and value.strip():
                    normalized, _ = normalize_city_name(value.strip(), default_city)
                    if normalized:
                        return normalized
        location = meta_payload.get("location")
        candidate = ""
        if isinstance(location, str):
            candidate = location.strip()
        elif isinstance(location, dict):
            for key in ("city", "name", "display", "text"):
                value = location.get(key)
                if isinstance(value, str) and value.strip():
                    candidate = value.strip()
                    break
        if not candidate:
            context_meta = meta_payload.get("context") or {}
            context_location = context_meta.get("location")
            if isinstance(context_location, str):
                candidate = context_location.strip()
            elif isinstance(context_location, dict):
                for key in ("city", "name"):
                    value = context_location.get(key)
                    if isinstance(value, str) and value.strip():
                        candidate = value.strip()
                        break
        normalized, _reason = normalize_city_name(candidate or default_city, default_city)
        return normalized or default_city

    def _decide_weather_city(
        self,
        *,
        query: str,
        weather_detail_payload: Dict[str, Any],
        meta_payload: Dict[str, Any],
    ) -> tuple[str, str]:
        """
        决策天气查询城市：query > meta.city > default。
        返回 (city_value, source)
        """
        default_city = self._settings.weather_default_city
        # 1) query 地点（仅当明确标记为 query 来源时才视为最高优先级）
        query_city = ""
        loc_source = weather_detail_payload.get("location_source") or ""
        if loc_source == "query":
            query_city = weather_detail_payload.get("location") or ""
        # 2) meta.city
        meta_city = ""
        city_field = meta_payload.get("city")
        if isinstance(city_field, str) and city_field.strip():
            meta_city = city_field.strip()
        elif isinstance(city_field, dict):
            meta_city = (city_field.get("name") or city_field.get("city") or "").strip()
        # 3) llm/location 默认给出的城市（仅在无 query/meta 时作为兜底）
        llm_city = ""
        if not query_city:
            llm_city = weather_detail_payload.get("location") or ""

        # 优先使用 query 中的地点（若合理）
        if query_city:
            city_value, _ = normalize_city_name(query_city, default_city)
            return city_value, "query"
        # 其次 meta.city
        if meta_city:
            city_value, _ = normalize_city_name(meta_city, default_city)
            return city_value, "meta"
        # 再次使用 llm 推测的城市
        if llm_city:
            city_value, _ = normalize_city_name(llm_city, default_city)
            return city_value, "llm"
        # 否则默认
        return default_city, "default"

    async def _get_local_weather_context(self, city: str) -> Optional[Dict[str, Any]]:
        """拉取并缓存本地天气摘要供 LLM 参考。"""
        if not self._weather_service or not self._weather_service.enabled:
            return None
        cache_key = city or self._settings.weather_default_city
        if self._local_weather_cache is not None and cache_key in self._local_weather_cache:
            cached = self._local_weather_cache[cache_key]
            if cached:
                return cached
        llm_info = {
            "location": city,
            "location_confidence": 0.95,
            "location_source": "context",
            "target_date": now_e8().date().isoformat(),
            "needs_realtime_data": True,
        }
        try:
            context = await self._weather_service.fetch(
                llm_info=llm_info,
                summary=None,
                needs_realtime=True,
                query="context-local-weather",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("local weather fetch failed", error=str(exc))
            return None
        if not context:
            return None
        summary = context.summary
        target_day = (context.derived_flags or {}).get("target_day") or {}
        current = context.current or {}
        current_parts: list[str] = []
        now_weather = current.get("weather")
        now_temp = current.get("temperature")
        now_humidity = current.get("sd")
        if now_weather:
            current_parts.append(str(now_weather))
        if now_temp not in (None, ""):
            current_parts.append(f"{now_temp}℃")
        if now_humidity:
            current_parts.append(f"湿度{now_humidity}")
        current_text = ""
        if current_parts:
            current_text = f"当前{'、'.join(current_parts)}"
        day_text = target_day.get("day_text") or target_day.get("night_text") or ""
        high_temp = target_day.get("high_temp")
        low_temp = target_day.get("low_temp")
        temp_phrase = ""
        if high_temp is not None and low_temp is not None:
            temp_phrase = f"{low_temp}~{high_temp}℃"
        elif high_temp is not None:
            temp_phrase = f"最高{high_temp}℃"
        elif low_temp is not None:
            temp_phrase = f"最低{low_temp}℃"
        precip_probability = target_day.get("precip_probability")
        precip_phrase = ""
        if isinstance(precip_probability, (float, int)):
            precip_phrase = f"降水概率{int(round(precip_probability * 100))}%"
        target_day_phrase_parts = []
        if day_text:
            target_day_phrase_parts.append(day_text)
        if temp_phrase:
            target_day_phrase_parts.append(temp_phrase)
        if precip_phrase:
            target_day_phrase_parts.append(precip_phrase)
        target_day_phrase = "、".join(target_day_phrase_parts)
        summary_current = f"{context.location} {current_text}" if current_text else ""
        summary_forecast = f"今日{target_day_phrase}" if target_day_phrase else ""
        if summary_current:
            summary_short = summary_current
        elif summary_forecast:
            summary_short = f"{context.location} {summary_forecast}"
        else:
            summary_short = summary
        meta = {
            "city": context.location,
            "summary": summary_short,
            "summary_current": summary_current,
            "summary_forecast": summary_forecast,
            "target_date": context.target_date.isoformat() if context.target_date else now_e8().date().isoformat(),
            "current": current,
            "target_day": target_day,
            "retrieved_at": now_e8().isoformat(),
        }
        if summary_short and summary_short != summary:
            meta["summary_short"] = summary_short
        if self._local_weather_cache is not None:
            self._local_weather_cache[cache_key] = meta
        return meta

    def _is_vague_temperature_query(self, query: str) -> bool:
        """判断是否为主观冷热/闷湿等环境或体感描述。"""
        q = (query or "").lower()
        if not q:
            return False
        # 明确询问冷热的句式，直接视作体感类问题
        question_tokens = ["热吗", "冷吗", "热不热", "冷不冷"]
        if any(tok in q for tok in question_tokens):
            return True
        subjective_tokens = ["好", "有点", "有些", "感觉", "觉得", "太", "挺", "特别", "非常"]
        temp_tokens = ["热", "冷", "闷", "潮", "晒", "湿", "风大", "凉"]
        has_subjective = any(tok in q for tok in subjective_tokens)
        has_temp = any(tok in q for tok in temp_tokens)
        return has_subjective and has_temp

    def _should_attach_local_weather(self, query: str) -> bool:
        if not query:
            return False
        # 体感温度/闷湿类表述：允许注入天气作为分析线索
        if self._is_vague_temperature_query(query):
            return True
        # 明确出现体温/发热等身体温度指标，也可参考当地天气进行综合判断
        body_temp_tokens = ["体温", "发烧", "发热", "温度高", "温度低"]
        if any(token in query for token in body_temp_tokens):
            return True
        # 明确天气/气温/降雨等环境类问题
        keywords = [
            "天气",
            "气温",
            "温度",
            "下雨",
            "降雨",
            "降温",
            "下雪",
            "刮风",
            "空气质量",
            "雾霾",
            "紫外线",
            "湿度",
        ]
        return any(keyword in query for keyword in keywords)

    async def _ensure_local_weather_meta(self, meta_payload: Dict[str, Any]) -> None:
        """在 meta 中填充 local_weather 上下文，供大模型推理参考。"""
        if meta_payload is None:
            return
        if (meta_payload.get("context") or {}).get("local_weather"):
            return
        city = self._resolve_context_city(meta_payload)
        local_weather = await self._get_local_weather_context(city)
        if not local_weather:
            logger.debug("inject_local_weather_context_failed", city=city)
            return
        context_meta = dict(meta_payload.get("context") or {})
        context_meta["local_weather"] = local_weather
        meta_payload["context"] = context_meta
        logger.debug(
            "inject_local_weather_context",
            city=local_weather.get("city"),
            summary=local_weather.get("summary"),
        )

    def _maybe_append_weather_hint(
        self,
        reply_message: str,
        *,
        query: str,
        meta_payload: Dict[str, Any],
        function_analysis: FunctionAnalysis,
        rule_source: str,
    ) -> str:
        """在健康/模糊场景下补充当地天气提示，帮助用户理解可能的环境因素。"""
        if rule_source == "rule":
            return reply_message
        # 非天气/非体感相关问题不应拼接天气提示，避免“答非所问”。
        if not self._should_attach_local_weather(query):
            return reply_message
        # 体感/模糊指令交由 LLM 自行判断是否引用天气，不再本地强制拼接
        if self._is_vague_temperature_query(query):
            return reply_message
        context_meta = (meta_payload or {}).get("context") or {}
        local_weather = context_meta.get("local_weather")
        if not isinstance(local_weather, dict):
            return reply_message
        if function_analysis.weather_summary:
            return reply_message
        if function_analysis.need_clarify:
            return reply_message
        if not reply_message:
            return reply_message
        city = local_weather.get("city") or ""
        # 如果回复中已提及温度、天气或城市，则不重复补充。
        key_tokens = ["℃", "温度", "天气", city]
        if any(token and token in reply_message for token in key_tokens):
            return reply_message
        current = local_weather.get("current") or {}
        target_day = local_weather.get("target_day") or {}
        current_desc: list[str] = []
        now_weather = current.get("weather")
        now_temp = current.get("temperature")
        now_humidity = current.get("sd")
        if now_weather:
            current_desc.append(str(now_weather))
        if now_temp not in (None, ""):
            current_desc.append(f"{now_temp}℃")
        if now_humidity:
            current_desc.append(f"湿度{now_humidity}")
        # 实况优先：若已有当前实况则不再拼接“今日预报”
        day_desc: list[str] = []
        if not current_desc:
            day_text = target_day.get("day_text") or target_day.get("night_text")
            if day_text:
                day_desc.append(str(day_text))
            high_temp = target_day.get("high_temp")
            low_temp = target_day.get("low_temp")
            if high_temp is not None and low_temp is not None:
                day_desc.append(f"{low_temp}~{high_temp}℃")
            elif high_temp is not None:
                day_desc.append(f"最高{high_temp}℃")
            elif low_temp is not None:
                day_desc.append(f"最低{low_temp}℃")
            precip_probability = target_day.get("precip_probability")
            if isinstance(precip_probability, (float, int)):
                day_desc.append(f"降水概率{int(round(precip_probability * 100))}%")
        hint_segments: list[str] = []
        if current_desc:
            hint_segments.append(f"当前{'、'.join(current_desc)}")
        if day_desc:
            hint_segments.append(f"今日{'、'.join(day_desc)}")
        summary_short = local_weather.get("summary_short") or local_weather.get("summary")
        core_hint = "，".join(hint_segments) if hint_segments else summary_short
        if not core_hint:
            return reply_message
        hint = f"{city}{core_hint}，请注意随时调整衣物或室内通风。" if city else f"{core_hint}，请注意随时调整衣物或室内通风。"
        trimmed = reply_message.rstrip()
        if trimmed and trimmed[-1] not in "。！？!?":
            trimmed += "。"
        augmented = f"{trimmed} {hint}"
        return augmented.strip()

    def _strip_irrelevant_weather_from_reply(
        self,
        reply_message: str,
        *,
        query: str,
        function_analysis: FunctionAnalysis,
        meta_payload: Dict[str, Any],
    ) -> str:
        """
        对“非天气/非体感”的问题，移除模型/兜底话术中不相关的天气尾巴。

        说明：
        - 目标是避免出现“数学题/逻辑题/常识题后面硬塞一句天气关怀”的体验问题。
        - 仅在确认当前问题不需要天气上下文时触发，避免误删真正的天气回答。
        """
        text = (reply_message or "").strip()
        if not text:
            return reply_message
        # 若用户明确涉及天气/体感/体温，则允许提天气
        if self._should_attach_local_weather(query):
            return reply_message
        # 若当前已进入天气链路（结构化字段或 summary），则允许提天气
        if function_analysis.weather_summary or function_analysis.weather_detail:
            return reply_message
        # 若 meta 中显式提供 local_weather（例如前端环境感知），但本轮 query 不需要天气，则不应扩展天气闲聊
        context_meta = (meta_payload or {}).get("context") or {}
        if isinstance(context_meta, dict) and isinstance(context_meta.get("local_weather"), dict):
            # 仍然视作“不需要天气”，继续走清理逻辑
            pass

        weather_tokens = [
            "天气",
            "气温",
            "温度",
            "湿度",
            "降水",
            "风力",
            "风大",
            "下雨",
            "雨具",
            "带伞",
            "晴",
            "多云",
            "阴",
            "小雨",
            "中雨",
            "大雨",
            "雷雨",
            "下雪",
            "保暖",
            "添衣",
            "防晒",
        ]
        # 以句号/问号/感叹号分段，剔除包含天气词的段落
        import re

        segments = re.split(r"(?<=[。！？!?])\\s*", text)
        kept: list[str] = []
        for seg in segments:
            s = (seg or "").strip()
            if not s:
                continue
            if any(tok in s for tok in weather_tokens):
                continue
            kept.append(s)
        cleaned = "".join(kept).strip()
        return cleaned or reply_message

    def _clean_safety_message(
        self,
        reply_message: str,
        *,
        function_analysis: FunctionAnalysis,
        query: str,
    ) -> str:
        """
        降低重复安全提示的频率：仅在高风险/不确定场景保留一次短提示。
        """
        if not reply_message:
            return reply_message
        safety_templates = [
            "小雅的建议仅供参考，如体温异常请及时咨询医生",
            "小雅的建议仅供参考，如有不适请及时咨询医生",
            "健康建议仅供参考，如有不适请及时就医",
        ]
        has_safety = any(t in reply_message for t in safety_templates)
        if not has_safety:
            return reply_message

        risk_tokens = [
            "监测",
            "医生",
            "问诊",
            "药",
            "用药",
            "服药",
            "发烧",
            "发热",
            "疼",
            "痛",
            "不适",
            "异常",
        ]
        result_text = function_analysis.result or ""
        high_risk = any(token in result_text for token in risk_tokens) or any(
            token in query for token in risk_tokens
        )

        # 去除重复提示
        core = reply_message
        for t in safety_templates:
            core = core.replace(t, "")
        core = core.strip()

        # 非高风险：直接去掉安全提示，保持主体回复
        if not high_risk:
            return core or reply_message

        # 高风险：仅保留一次最短提示
        shortest = min((t for t in safety_templates if t in reply_message), key=len, default="")
        if not shortest:
            return core or reply_message
        if core and core[-1] not in "。！？!?":
            core += "。"
        return f"{core} {shortest}".strip()

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
        if getattr(payload, "city", None):
            meta_payload["city"] = payload.city
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
                if self._should_attach_local_weather(payload.query):
                    await self._ensure_local_weather_meta(meta_payload)
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
                # 闹钟过时检测：若解析时间已早于当前时间，则提示澄清，不返回过期时间
                if function_analysis.result in {"新增闹钟"} and function_analysis.parsed_time:
                    try:
                        parsed_dt = datetime.fromisoformat(function_analysis.parsed_time)
                        if parsed_dt.tzinfo is None:
                            parsed_dt = parsed_dt.replace(tzinfo=EAST_EIGHT)
                        now_ts = now_e8()
                        if parsed_dt <= now_ts:
                            function_analysis.parsed_time = None
                            function_analysis.target = ""
                            function_analysis.need_clarify = True
                            # 交由 LLM 生成澄清话术，避免本地固定模板
                            reply_message = function_analysis.clarify_message or reply_message
                    except Exception:
                        pass
                if not (meta_payload.get("context") or {}).get("local_weather"):
                    if (
                        weather_detail_payload
                        or ("天气" in (function_analysis.result or ""))
                        or (function_analysis.need_clarify and self._should_attach_local_weather(payload.query))
                    ):
                        await self._ensure_local_weather_meta(meta_payload)

            # 农历转公历：对“农历X月X是什么时候”类查询，使用 LLM 判定策略，再用 lunar_python 确定性转换并填充 target/msg
            lunar_reply = await self._maybe_resolve_lunar_calendar(
                session_id=session_id,
                query=payload.query,
                function_analysis=function_analysis,
            )
            if lunar_reply:
                # 对农历→公历转换类问题，优先使用确定性播报，避免主 LLM 话术掺入无关内容造成不一致
                reply_message = lunar_reply

            if (
                self._weather_service
                and self._weather_service.enabled
            ):
                # 若已有细节按细节走；若为空但结果/summary 显示天气需求，则用 meta/query 城市兜底构造最小 detail 以触发拉取
                if not weather_detail_payload and (
                    ("天气" in (function_analysis.result or ""))
                    or function_analysis.weather_summary
                ):
                    city_value, city_source = self._decide_weather_city(
                        query=payload.query,
                        weather_detail_payload={"location": ""},
                        meta_payload=meta_payload,
                    )
                    weather_detail_payload = {
                        "location": city_value,
                        "location_source": city_source,
                        "location_confidence": 0.9 if city_source != "default" else 0.6,
                        "target_date": function_analysis.parsed_time,
                        "target_date_text": function_analysis.time_text,
                    }
                if not weather_detail_payload:
                    weather_context = None
                else:
                    weather_fetch_start = perf_counter()
                    used_query_city = False
                    try:
                        if weather_detail_payload:
                            # 按优先级决策城市：query > meta.city > default
                            city_value, city_source = self._decide_weather_city(
                                query=payload.query,
                                weather_detail_payload=weather_detail_payload,
                                meta_payload=meta_payload,
                            )
                            # 如果 query 中没有解析到城市，尝试补全：
                            # - 当已使用 meta.city（定位城市）时：不额外调用 LLM，避免覆盖定位城市
                            # - 当没有 meta.city 时：允许用轻量 LLM 从 query 里抽取城市
                            if city_source != "query":
                                city_from_query, _reason = extract_city_from_query(
                                    payload.query,
                                    self._settings.weather_default_city,
                                )
                                if city_from_query:
                                    city_value, _ = normalize_city_name(
                                        city_from_query,
                                        self._settings.weather_default_city,
                                    )
                                    city_source = "query"
                                elif city_source != "meta":
                                    city_from_query = await self._llm_extract_city(
                                        {"query": payload.query}
                                    )
                                    if city_from_query:
                                        city_value, _ = normalize_city_name(
                                            city_from_query,
                                            self._settings.weather_default_city,
                                        )
                                        city_source = "query"
                            weather_detail_payload["location"] = city_value
                            weather_detail_payload["location_source"] = city_source
                            weather_detail_payload["location_confidence"] = max(0.9, float(weather_detail_payload.get("location_confidence") or 0.0)) if city_source == "query" else max(float(weather_detail_payload.get("location_confidence") or 0.0), 0.8)
                            used_query_city = city_source == "query"
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
                if used_query_city:
                    merged_detail["location_source"] = "query"
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

                if function_analysis.weather_summary:
                    reply_message = await self._generate_weather_reply_text(
                        query=payload.query,
                        summary=function_analysis.weather_summary,
                        detail=None,
                    )
                elif base_summary:
                    reply_message = await self._generate_weather_reply_text(
                        query=payload.query,
                        summary=base_summary,
                        detail=None,
                    )

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
        detail_meta = function_analysis.weather_detail or {}
        if detail_meta:
            location_name = (detail_meta.get("location") or "").strip()
            if location_name and location_name.endswith("市") and len(location_name) <= 2 and location_name[:1] in _NUMERAL_TOKENS:
                default_city = self._settings.weather_default_city
                detail_meta["location"] = default_city
                detail_meta["location_source"] = "default"
                function_analysis.weather_detail = detail_meta
                if function_analysis.weather_summary:
                    function_analysis.weather_summary = function_analysis.weather_summary.replace(location_name, default_city)
        use_fallback = False
        # 对 need_clarify 场景，不使用本地兜底，完全依赖 LLM/clarify_message
        is_unknown_clarify = not function_analysis.result and function_analysis.need_clarify
        if not function_analysis.need_clarify:
            if not trimmed_reply:
                use_fallback = True
            elif function_analysis.need_clarify and not function_analysis.clarify_message and not is_unknown_clarify:
                use_fallback = True

        reply_origin = "rule" if rule_match else "llm"
        if use_fallback:
            fallback_candidate = trimmed_reply or (function_analysis.result or "")
            response_message = _compose_response_message(function_analysis, fallback_candidate)
            reply_source = reply_origin if rule_match else "fallback"
        else:
            response_message = trimmed_reply
            reply_source = reply_origin

        response_message = self._clean_safety_message(
            response_message,
            function_analysis=function_analysis,
            query=payload.query,
        )
        response_message = self._maybe_append_weather_hint(
            response_message,
            query=payload.query,
            meta_payload=meta_payload,
            function_analysis=function_analysis,
            rule_source=reply_origin,
        )
        response_message = self._strip_irrelevant_weather_from_reply(
            response_message,
            query=payload.query,
            function_analysis=function_analysis,
            meta_payload=meta_payload,
        )

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

        fa_result = (function_analysis.result or "").strip()
        fa_target = (function_analysis.target or "").strip()
        selection_candidates = (
            self._extract_user_candidates(meta_payload, context)
            if fa_result in REQUIRES_SELECTION_RESULTS
            else []
        )
        requires_selection = bool(function_analysis.need_clarify) or (
            fa_result in REQUIRES_SELECTION_RESULTS and not fa_target and bool(selection_candidates)
        )

        # 对需要选择用户的功能：优先使用候选用户纠正/补全 target；若仍无法确定则触发二次询问
        if fa_result in REQUIRES_SELECTION_RESULTS:
            candidates = selection_candidates
            if candidates:
                # 1) 已有 target 但不在候选名单：尝试模糊匹配，否则清空
                if fa_target and fa_target not in candidates:
                    matched = self._match_candidate(fa_target, candidates)
                    if matched:
                        function_analysis.target = matched
                        fa_target = matched
                    else:
                        function_analysis.target = ""
                        fa_target = ""

                # 2) 缺少 target：若只有一个候选直接采用；多候选则生成二次询问话术
                if not fa_target:
                    if len(candidates) == 1:
                        function_analysis.target = candidates[0]
                        fa_target = candidates[0]
                    elif len(candidates) > 1 and not function_analysis.need_clarify:
                        function_analysis.need_clarify = True
                        clarification = await self._generate_structured_reply(
                            session_id=session_id,
                            query=payload.query,
                            function_analysis=function_analysis,
                            conversation_state=context,
                            meta=meta_payload,
                        )
                        if clarification:
                            function_analysis.clarify_message = clarification
                            response_message = clarification
                        requires_selection = True

                selection_candidates = candidates
                requires_selection = bool(function_analysis.need_clarify) or (
                    fa_result in REQUIRES_SELECTION_RESULTS and not fa_target and bool(selection_candidates)
                )

        detail_meta = function_analysis.weather_detail or {}
        location_name = (detail_meta.get("location") or "").strip()
        if location_name and any(token in location_name for token in _NUMERAL_TOKENS):
            default_city = self._settings.weather_default_city
            sanitized_detail = {
                **detail_meta,
                "location": default_city,
                "location_source": "default",
                "location_confidence": min(0.5, detail_meta.get("location_confidence") or 0.5),
            }
            function_analysis.weather_detail = sanitized_detail
            if function_analysis.weather_summary:
                function_analysis.weather_summary = function_analysis.weather_summary.replace(location_name, default_city)
            response_message = response_message.replace(location_name, default_city)
        elif detail_meta:
            query_city, _ = extract_city_from_query(payload.query, self._settings.weather_default_city)
            if query_city and query_city == location_name:
                detail_meta["location_source"] = "query"

        # 若没有回复文本但有澄清语，优先使用澄清语
        trimmed_reply = (response_message or "").strip()
        if not trimmed_reply and function_analysis.need_clarify and function_analysis.clarify_message:
            response_message = function_analysis.clarify_message

        # 记录会话：以最终 response_message/function_analysis 为准
        self._conversation_manager.update_state(
            session_id=session_id,
            query=payload.query,
            response_message=response_message,
            function_analysis=function_analysis,
            raw_llm_output=raw_output,
            user_candidates=context.user_candidates,
        )

        return CommandResponse(
            code=200,
            msg=response_message,
            sessionId=session_id,
            requires_selection=requires_selection,
            function_analysis=function_analysis,
        )
