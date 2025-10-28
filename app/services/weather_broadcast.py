from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from cachetools import TTLCache
from loguru import logger

from app.schemas.response import FunctionAnalysis

if TYPE_CHECKING:
    from app.services.llm_client import DoubaoClient
    from app.services.weather_service import WeatherContext


@dataclass(slots=True)
class WeatherBroadcastResult:
    message: Optional[str]
    confidence: float
    metadata: Dict[str, Any]


class WeatherBroadcastGenerator:
    """使用大模型生成气象播报文案的轻量封装。"""

    def __init__(
        self,
        llm_client: Optional["DoubaoClient"],
        *,
        enabled: bool = True,
        cache_ttl: int = 300,
    ) -> None:
        self._llm_client = llm_client
        self._enabled = bool(enabled and llm_client)
        self._cache: TTLCache[Tuple[str, str, str], WeatherBroadcastResult] = TTLCache(
            maxsize=128,
            ttl=cache_ttl,
        )

    def enabled(self) -> bool:
        return self._enabled

    async def generate(
        self,
        weather_context: "WeatherContext",
        analysis: FunctionAnalysis,
        user_query: str,
    ) -> WeatherBroadcastResult:
        if not self._enabled or not self._llm_client:
            return WeatherBroadcastResult(None, 0.0, {})

        cache_key = self._build_cache_key(weather_context, analysis, user_query)
        if cache_key in self._cache:
            return self._cache[cache_key]

        payload = self._build_payload(weather_context, analysis, user_query)
        system_prompt = self._build_system_prompt(weather_context)

        try:
            _, parsed = await self._llm_client.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather broadcast llm failed", error=str(exc))
            result = WeatherBroadcastResult(None, 0.0, {"error": str(exc)})
            self._cache[cache_key] = result
            return result

        if not isinstance(parsed, dict):
            logger.warning("weather broadcast llm returned non-dict", raw=parsed)
            result = WeatherBroadcastResult(None, 0.0, {"raw": parsed})
            self._cache[cache_key] = result
            return result

        message = str(parsed.get("broadcast_message") or "").strip()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        metadata = {
            "raw": parsed,
        }
        result = WeatherBroadcastResult(message or None, confidence, metadata)
        self._cache[cache_key] = result
        return result

    def _build_cache_key(
        self,
        weather_context: "WeatherContext",
        analysis: FunctionAnalysis,
        user_query: str,
    ) -> Tuple[str, str, str]:
        location = weather_context.location or ""
        date_key = weather_context.target_date.isoformat() if weather_context.target_date else "NA"
        condition_key = (
            f"{analysis.weather_condition}|{analysis.weather_judgement}|{analysis.weather_evidence}"
        )
        query_key = user_query.strip()
        return (location + "::" + date_key, condition_key, query_key)

    def _build_payload(
        self,
        weather_context: "WeatherContext",
        analysis: FunctionAnalysis,
        user_query: str,
    ) -> Dict[str, Any]:
        weather_payload = weather_context.to_prompt_dict()
        if analysis.weather_condition:
            weather_payload["weather_condition"] = analysis.weather_condition
        if analysis.weather_judgement:
            weather_payload["weather_judgement"] = analysis.weather_judgement
        if analysis.weather_evidence:
            weather_payload["weather_evidence"] = analysis.weather_evidence
        detail = analysis.weather_detail or {}
        if detail:
            weather_payload["detail_override"] = detail
        return {
            "weather_data": weather_payload,
            "user_question": user_query,
        }

    def _build_system_prompt(self, weather_context: "WeatherContext") -> str:
        return (
            "你是“小雅数字健康机器人”的气象播报员，请严格遵守以下规则生成 json：\n"
            "1. 输出必须是 json_object，字段为 {\"broadcast_message\": \"…\", \"confidence\": 0~1}；\n"
            "2. 只能依据提供的 weather_data，禁止编造；数据缺失时要明确说明；\n"
            "3. 播报需要包含地点、日期标签、天气现象、温度范围、必要提醒；\n"
            "4. 若给定 weather_condition/weather_judgement，需要在播报中直接回答对应问题；\n"
            "5. 若 location_source 为 default，则说明使用默认城市；若为 llm，则说明来源于模型解析；若为 llm_low，则提示城市为模型推测且需要用户确认；\n"
            "6. 若无法生成合规播报，返回空串并将原因写入 broadcast_message；\n"
            "7. 字符串内避免换行和多余标点，语气保持温和专业。"
        )
