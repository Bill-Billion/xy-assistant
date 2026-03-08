from __future__ import annotations

import json
import math
import re
import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Dict, Iterable, Optional, Tuple, TYPE_CHECKING

import httpx
from cachetools import TTLCache
from loguru import logger
from dateparser import parse as dateparser_parse

from app.services.weather_client import WeatherAPIError, WeatherClient, WeatherClientConfig
from app.utils.time_utils import now_e8, parse_weather_date
from app.utils.location_utils import normalize_city_name

if TYPE_CHECKING:
    from app.services.llm_client import DoubaoClient


@dataclass(slots=True)
class GeoPoint:
    name: str
    latitude: float
    longitude: float


# _PRESET_GEO_POINTS 列举常用城市的地理坐标，便于快速定位
_PRESET_GEO_POINTS: Dict[str, GeoPoint] = {
    "北京": GeoPoint("北京市", 39.9042, 116.4074),
    "北京市": GeoPoint("北京市", 39.9042, 116.4074),
    "上海": GeoPoint("上海市", 31.2304, 121.4737),
    "上海市": GeoPoint("上海市", 31.2304, 121.4737),
    "广州": GeoPoint("广州市", 23.1291, 113.2644),
    "广州市": GeoPoint("广州市", 23.1291, 113.2644),
    "深圳": GeoPoint("深圳市", 22.5431, 114.0579),
    "深圳市": GeoPoint("深圳市", 22.5431, 114.0579),
    "武汉": GeoPoint("武汉市", 30.5931, 114.3054),
    "武汉市": GeoPoint("武汉市", 30.5931, 114.3054),
    "杭州": GeoPoint("杭州市", 30.2741, 120.1551),
    "杭州市": GeoPoint("杭州市", 30.2741, 120.1551),
    "成都": GeoPoint("成都市", 30.5728, 104.0668),
    "成都市": GeoPoint("成都市", 30.5728, 104.0668),
    "南京": GeoPoint("南京市", 32.0603, 118.7969),
    "南京市": GeoPoint("南京市", 32.0603, 118.7969),
    "天津": GeoPoint("天津市", 39.3434, 117.3616),
    "天津市": GeoPoint("天津市", 39.3434, 117.3616),
    "西安": GeoPoint("西安市", 34.3416, 108.9398),
    "西安市": GeoPoint("西安市", 34.3416, 108.9398),
    "重庆": GeoPoint("重庆市", 29.5630, 106.5516),
    "重庆市": GeoPoint("重庆市", 29.5630, 106.5516),
    "长沙": GeoPoint("长沙市", 28.2278, 112.9389),
    "长沙市": GeoPoint("长沙市", 28.2278, 112.9389),
}


@dataclass(slots=True)
class LLMExtraction:
    city: str
    province: str
    country: str
    datetime_text: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "province": self.province,
            "country": self.country,
            "datetime": self.datetime_text,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class LLMDateExtraction:
    resolved_date: date
    confidence: float
    reason: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_date": self.resolved_date.isoformat(),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(slots=True)
class WeatherDaily:
    day: date
    daytime_text: str
    nighttime_text: str
    high_temp: Optional[int]
    low_temp: Optional[int]
    precipitation: Optional[str]
    daytime_wind: Optional[str]
    night_wind: Optional[str]
    raw: Dict[str, Any]

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "WeatherDaily":
        day_str = payload.get("day")
        day_date = date.fromisoformat(
            f"{day_str[0:4]}-{day_str[4:6]}-{day_str[6:8]}"
        )
        return cls(
            day=day_date,
            daytime_text=payload.get("day_weather") or "",
            nighttime_text=payload.get("night_weather") or "",
            high_temp=_safe_int(payload.get("day_air_temperature")),
            low_temp=_safe_int(payload.get("night_air_temperature")),
            precipitation=payload.get("jiangshui"),
            daytime_wind=_merge_wind(payload.get("day_wind_direction"), payload.get("day_wind_power")),
            night_wind=_merge_wind(payload.get("night_wind_direction"), payload.get("night_wind_power")),
            raw=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.day.isoformat(),
            "daytime": self.daytime_text,
            "nighttime": self.nighttime_text,
            "high": self.high_temp,
            "low": self.low_temp,
            "precipitation": self.precipitation,
            "daytime_wind": self.daytime_wind,
            "night_wind": self.night_wind,
        }


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value in ("_", None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _merge_wind(direction: Optional[str], power: Optional[str]) -> Optional[str]:
    direction = (direction or "").strip()
    power = (power or "").strip()
    if not direction and not power:
        return None
    if direction and power:
        return f"{direction} {power}"
    return direction or power


def _parse_percentage(value: Any) -> Optional[float]:
    if value in (None, "", "_"):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1]
    try:
        return max(0.0, min(1.0, float(text) / 100.0))
    except ValueError:
        return None


def _analyze_daily(daily: WeatherDaily) -> Dict[str, Any]:
    day_text = daily.daytime_text or ""
    night_text = daily.nighttime_text or ""
    combined = day_text + night_text
    combined_lower = combined.lower()

    def _contains(words: Iterable[str]) -> bool:
        return any(word in combined for word in words)

    has_rain = _contains(["雨", "雷阵雨", "阵雨", "小雨", "中雨", "大雨", "暴雨", "雷雨", "毛毛雨"])
    has_snow = _contains(["雪", "冰雹", "雨夹雪", "冻雨"])
    is_sunny = ("晴" in combined) and not has_rain and not has_snow
    is_cloudy = _contains(["多云", "阴"]) and not has_rain and not has_snow

    high = daily.high_temp
    low = daily.low_temp
    precip_probability = _parse_percentage(daily.raw.get("jiangshui"))

    is_hot = high is not None and high >= 30
    is_cold = low is not None and low <= 5

    wind_info = daily.daytime_wind or daily.night_wind

    return {
        "day_text": day_text,
        "night_text": night_text,
        "high_temp": high,
        "low_temp": low,
        "precip_probability": precip_probability,
        "has_rain": has_rain,
        "has_snow": has_snow,
        "is_sunny": is_sunny,
        "is_cloudy": is_cloudy,
        "is_hot": is_hot,
        "is_cold": is_cold,
        "wind": wind_info,
    }


def _derive_flags(
    location: str,
    target_date: Optional[date],
    daily_items: Iterable[WeatherDaily],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    daily_list = list(daily_items)
    if not daily_list:
        return {}
    daily_map = {item.day: item for item in daily_list}

    today = now_e8().date()
    selected_day = target_date
    if not selected_day or selected_day not in daily_map:
        if today in daily_map:
            selected_day = today
        else:
            selected_day = daily_list[0].day

    selected_daily = daily_map.get(selected_day)
    analysis = _analyze_daily(selected_daily) if selected_daily else {}

    current_weather = {
        "weather": current.get("weather"),
        "temperature": _safe_int(current.get("temperature")),
        "humidity": _parse_percentage(current.get("sd")),
        "wind_power": current.get("wind_power"),
        "wind_direction": current.get("wind_direction"),
        "aqi": current.get("aqiDetail", {}).get("quality") if isinstance(current.get("aqiDetail"), dict) else None,
    }

    return {
        "location": location,
        "target_date": selected_day.isoformat() if selected_day else None,
        "target_day": analysis,
        "current": current_weather,
    }


class WeatherContext:
    """封装天气数据，便于对外暴露摘要/细节。"""

    def __init__(
        self,
        location: str,
        point: GeoPoint,
        target_date: Optional[date],
        daily: Iterable[WeatherDaily],
        current: Optional[Dict[str, Any]],
        derived_flags: Optional[Dict[str, Any]] = None,
        location_source: str = "rule",
        target_date_source: str = "query",
        llm_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.location = location
        self.point = point
        self.target_date = target_date
        self._daily = list(daily)
        self._daily_map = {item.day: item for item in self._daily}
        self.current = current or {}
        self.derived_flags = derived_flags or {}
        self.location_source = location_source
        self.target_date_source = target_date_source
        self.llm_metadata = llm_metadata or {}

    def _select_day(self) -> Optional[WeatherDaily]:
        if self.target_date and self.target_date in self._daily_map:
            return self._daily_map[self.target_date]
        base = now_e8().date()
        if base in self._daily_map:
            return self._daily_map[base]
        return self._daily[0] if self._daily else None

    @property
    def summary(self) -> str:
        llm_summary = self.llm_metadata.get("llm_summary")
        if llm_summary:
            return llm_summary
        pieces: list[str] = []
        location_display = self.location
        if self.location_source == "default":
            location_display += ""
        elif self.location_source == "llm":
            location_display += "（模型解析）"
        elif self.location_source == "llm_low":
            location_display += "（模型推测，待确认）"
        selected = self._select_day()
        if self.current:
            weather = self.current.get("weather")
            temp = self.current.get("temperature")
            humidity = self.current.get("sd")
            parts = []
            if weather:
                parts.append(weather)
            if temp:
                parts.append(f"{temp}℃")
            if humidity:
                parts.append(f"湿度{humidity}")
            if parts:
                pieces.append(f"{location_display}当前{''.join(parts)}")
        if selected:
            label = _describe_date(selected.day, self.target_date)
            temp_phrase = ""
            if selected.high_temp is not None and selected.low_temp is not None:
                temp_phrase = f"{selected.low_temp}~{selected.high_temp}℃"
            elif selected.high_temp is not None:
                temp_phrase = f"最高{selected.high_temp}℃"
            elif selected.low_temp is not None:
                temp_phrase = f"最低{selected.low_temp}℃"
            day_text = selected.daytime_text or selected.nighttime_text
            parts = [location_display, label]
            if day_text:
                parts.append(day_text)
            if temp_phrase:
                parts.append(temp_phrase)
            pieces.append(" ".join(parts))
        if not pieces:
            pieces.append(f"{self.location}暂时无法获取实时天气，请稍后重试。")
        return "。".join(pieces)

    def to_prompt_dict(self, max_days: int = 5) -> Dict[str, Any]:
        return {
            "location": self.location,
            "coordinate": {"lat": self.point.latitude, "lng": self.point.longitude},
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "summary": self.summary,
            "current": self.current or {},
            "daily": [item.to_dict() for item in self._daily[:max_days]],
            "derived_flags": self.derived_flags,
            "location_source": self.location_source,
            "target_date_source": self.target_date_source,
            "llm_metadata": self.llm_metadata,
        }

    def to_function_detail(self, max_days: int = 7) -> Dict[str, Any]:
        return {
            "location": self.location,
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "coordinate": {"lat": self.point.latitude, "lng": self.point.longitude},
            "current": self.current or {},
            "forecast": [item.to_dict() for item in self._daily[:max_days]],
            "derived_flags": self.derived_flags,
            "location_source": self.location_source,
            "target_date_source": self.target_date_source,
            "llm_metadata": self.llm_metadata,
            "needs_realtime_data": self.llm_metadata.get("needs_realtime_data", False),
        }

    def clone(
        self,
        *,
        location_source: Optional[str] = None,
        target_date_source: Optional[str] = None,
        llm_metadata: Optional[Dict[str, Any]] = None,
    ) -> "WeatherContext":
        """复制上下文以便在缓存命中时调整元信息。"""
        return WeatherContext(
            location=self.location,
            point=self.point,
            target_date=self.target_date,
            daily=self._daily,
            current=self.current,
            derived_flags=self.derived_flags,
            location_source=location_source or self.location_source,
            target_date_source=target_date_source or self.target_date_source,
            llm_metadata=llm_metadata if llm_metadata is not None else self.llm_metadata,
        )


class WeatherService:
    """聚合地理解析与天气 API 调用，向上层提供结构化结果。"""

    _LOCATION_PATTERN = re.compile(
        r"(?P<city>[\u4e00-\u9fa5]{2,8}?)(?:省|市|区|县|州|盟|自治区|特别行政区)?"
        r"(?=.*?(?:天气|气温|温度|空气质量|下雨|降雨|雨|晴|雪|风|阴|雾|霾))"
    )
    _INVALID_CITIES = {"今天", "明天", "后天", "现在", "近期"}
    _AMBIGUOUS_CITY_TOKENS = [
        "什么",
        "多少",
        "哪个",
        "哪儿",
        "哪里",
        "哪",
        "啥",
        "如何",
        "是否",
        "么",
        "吗",
        "嘛",
    ]
    _TIME_TOKENS = [
        "今天",
        "明天",
        "后天",
        "本周",
        "这周",
        "上周",
        "下周",
        "这周末",
        "本周末",
        "下周末",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
        "星期天",
        "这周一",
        "这周二",
        "这周三",
        "这周四",
        "这周五",
        "这周六",
        "这周日",
        "这星期",
        "本周日",
        "下周日",
        "下星期天",
    ]
    _DATE_PATTERNS = [
        re.compile(r"\d{4}年\d{1,2}月\d{1,2}日"),
        re.compile(r"\d{1,2}月\d{1,2}日"),
        re.compile(r"\d{1,2}号"),
    ]
    _TIME_TOKENS_SORTED = sorted(_TIME_TOKENS, key=len, reverse=True)
    _STRICT_REALTIME_TIME_TOKENS = (
        "现在",
        "当前",
        "此刻",
        "此时",
        "实时",
        "外面",
        "室外",
        "外边",
        "外头",
    )
    _STRICT_REALTIME_WEATHER_TOKENS = (
        "天气",
        "气温",
        "温度",
        "多少度",
        "几度",
        "℃",
        "下雨",
        "降雨",
        "刮风",
        "风力",
        "风大",
        "空气质量",
        "雾霾",
        "湿度",
        "紫外线",
    )

    def _is_strict_realtime_query(self, query: str) -> bool:
        """判断是否为“现在/室外”等需要更及时更新的天气查询。"""
        q = (query or "").strip()
        if not q:
            return False
        q_lower = q.lower()
        has_time_hint = any(token in q for token in self._STRICT_REALTIME_TIME_TOKENS)
        has_weather_hint = any(token in q for token in self._STRICT_REALTIME_WEATHER_TOKENS) or "°c" in q_lower
        return has_time_hint and has_weather_hint

    def _is_realtime_cache_fresh(self, cached: "WeatherContext") -> bool:
        ttl = int(getattr(self, "_realtime_cache_ttl", 0) or 0)
        if ttl <= 0:
            return False
        meta = getattr(cached, "llm_metadata", None)
        if not isinstance(meta, dict):
            return False
        raw_ts = meta.get("api_retrieved_at_ts")
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            return False
        return (time.monotonic() - ts) <= ttl

    def __init__(
        self,
        settings,
        *,
        client: WeatherClient | None = None,
        llm_client: Optional["DoubaoClient"] = None,
    ) -> None:
        self._settings = settings
        self._enabled = bool(
            settings.weather_api_enabled and settings.weather_api_app_code
        )
        if self._enabled:
            self._client = client or WeatherClient(
                WeatherClientConfig(
                    app_code=settings.weather_api_app_code,
                    base_url=settings.weather_api_base_url,
                    timeout=settings.weather_api_timeout,
                    verify_ssl=settings.weather_api_verify_ssl,
                )
            )
        else:
            self._client = client
        self._llm_client = llm_client
        self._llm_enabled = bool(getattr(settings, "weather_llm_enabled", True) and llm_client)
        self._llm_confidence_threshold = getattr(settings, "weather_llm_confidence_threshold", 0.6)
        self._llm_low_confidence_threshold = getattr(settings, "weather_llm_low_confidence_threshold", 0.3)
        self._default_point = GeoPoint(
            name=settings.weather_default_city,
            latitude=settings.weather_default_lat,
            longitude=settings.weather_default_lon,
        )
        self._weather_cache: TTLCache[Tuple[str, str], WeatherContext] = TTLCache(
            maxsize=128,
            ttl=settings.weather_cache_ttl,
        )
        self._geo_cache: TTLCache[str, GeoPoint] = TTLCache(
            maxsize=256,
            ttl=settings.weather_geo_cache_ttl,
        )
        self._realtime_cache_ttl = max(0, int(getattr(settings, "weather_realtime_cache_ttl", 60) or 0))
        self._throttle_lock = asyncio.Lock()
        self._last_fetch_ts = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def fetch(
        self,
        *,
        llm_info: Dict[str, Any],
        summary: Optional[str],
        needs_realtime: bool,
        query: str = "",
    ) -> Optional[WeatherContext]:
        if not llm_info:
            return None
        if not isinstance(llm_info, dict):
            llm_info = dict(llm_info)

        def _to_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        raw_location = str(llm_info.get("location") or "").strip()
        if not raw_location:
            return None

        location_confidence = _to_float(llm_info.get("location_confidence"))
        if location_confidence is None:
            location_confidence = _to_float((llm_info.get("location_info") or {}).get("confidence"))

        normalized_name, normalize_reason = normalize_city_name(raw_location, self._default_point.name)
        location_name = normalized_name

        provided_source = llm_info.get("location_source")

        if normalize_reason in {"empty", "numeric", "short"}:
            location_source = "default"
            location_confidence = 0.3
            llm_info["location"] = location_name
            llm_info["location_confidence"] = location_confidence
        else:
            if provided_source in {"query", "rule", "meta", "context"}:
                location_source = str(provided_source)
                location_confidence = max(location_confidence or 0.0, 0.85)
            else:
                if location_confidence is not None and location_confidence >= self._llm_confidence_threshold:
                    location_source = "llm"
                elif location_confidence is not None and location_confidence >= self._llm_low_confidence_threshold:
                    location_source = "llm_low"
                else:
                    location_source = "llm_low" if location_confidence is not None else "llm"
                if normalize_reason == "match" and (location_confidence or 0.0) < 0.8:
                    location_confidence = 0.8
        llm_info["location_source"] = location_source

        target_iso = str(llm_info.get("target_date") or "").strip()
        target_date = None
        target_date_source = "default"
        if target_iso:
            try:
                target_date = datetime.fromisoformat(target_iso).date()
                target_date_source = "llm"
            except ValueError:
                target_iso = ""

        geo_point = await self._resolve_point(location_name)

        cache_key = (geo_point.name, target_date.isoformat() if target_date else "NA")
        base_metadata: Dict[str, Any] = {
            "llm_summary": summary or "",
            "llm_info": llm_info,
            "needs_realtime_data": needs_realtime,
        }
        strict_realtime = bool(needs_realtime) and self._is_strict_realtime_query(query)

        if not needs_realtime or not self._enabled:
            base_metadata.setdefault("api_retrieved_at", now_e8().isoformat())
            base_metadata.setdefault("api_retrieved_at_ts", time.monotonic())
            context = WeatherContext(
                location=geo_point.name,
                point=geo_point,
                target_date=target_date,
                daily=[],
                current={},
                derived_flags={},
                location_source=location_source,
                target_date_source=target_date_source,
                llm_metadata=base_metadata,
            )
            self._weather_cache[cache_key] = context
            logger.debug(
                "weather summary from llm",
                location=geo_point.name,
                query=query,
            )
            return context

        if cache_key in self._weather_cache:
            cached = self._weather_cache[cache_key]
            if strict_realtime and not self._is_realtime_cache_fresh(cached):
                try:
                    del self._weather_cache[cache_key]
                except KeyError:
                    pass
            else:
                cached.llm_metadata.update(base_metadata)
                return cached.clone(
                    location_source=location_source,
                    target_date_source=target_date_source,
                    llm_metadata=cached.llm_metadata,
                )

        overall_start = perf_counter()
        body: Optional[Dict[str, Any]] = None
        attempts = 2 if needs_realtime else 1
        for attempt in range(attempts):
            fetch_start = perf_counter()
            try:
                if not self._client:
                    return None
                if needs_realtime:
                    async with self._throttle_lock:
                        now_ts = time.monotonic()
                        wait_time = 1.0 - (now_ts - self._last_fetch_ts)
                        if wait_time > 0:
                            await asyncio.sleep(wait_time)
                        self._last_fetch_ts = time.monotonic()
                        body = await self._client.get_forecast(
                            geo_point.latitude,
                            geo_point.longitude,
                            need_more_day=True,
                        )
                else:
                    body = await self._client.get_forecast(
                        geo_point.latitude,
                        geo_point.longitude,
                        need_more_day=True,
                    )
                logger.debug(
                    "timing weather_service",
                    step="weather_api",
                    duration=round(perf_counter() - fetch_start, 3),
                    location=geo_point.name,
                )
                break
            except WeatherAPIError as exc:
                logger.warning(
                    "weather fetch failed",
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt + 1 >= attempts:
                    base_metadata["api_failed"] = True
                    base_metadata["api_error"] = str(exc)
                    body = None
                    break
                await asyncio.sleep(0.8)
            except httpx.HTTPError as exc:
                logger.warning(
                    "weather http error",
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt + 1 >= attempts:
                    base_metadata["api_failed"] = True
                    base_metadata["api_error"] = str(exc)
                    body = None
                    break
                await asyncio.sleep(0.8)

        if not body:
            base_metadata.setdefault("api_retrieved_at", now_e8().isoformat())
            base_metadata.setdefault("api_retrieved_at_ts", time.monotonic())
            context = WeatherContext(
                location=geo_point.name,
                point=geo_point,
                target_date=target_date,
                daily=[],
                current={},
                derived_flags={},
                location_source=location_source,
                target_date_source=target_date_source,
                llm_metadata=base_metadata,
            )
            self._weather_cache[cache_key] = context
            return context

        base_metadata.setdefault("api_retrieved_at", now_e8().isoformat())
        base_metadata.setdefault("api_retrieved_at_ts", time.monotonic())
        daily_items = _parse_daily(body)
        current = body.get("now") or {}

        derived_flags = _derive_flags(geo_point.name, target_date, daily_items, current)
        context = WeatherContext(
            location=geo_point.name,
            point=geo_point,
            target_date=target_date,
            daily=daily_items,
            current=current,
            derived_flags=derived_flags,
            location_source=location_source,
            target_date_source=target_date_source,
            llm_metadata=base_metadata,
        )
        self._weather_cache[cache_key] = context
        logger.debug(
            "timing weather_service",
            step="total",
            duration=round(perf_counter() - overall_start, 3),
            location=geo_point.name,
            query=query,
        )
        return context

    def _extract_location(self, query: str) -> Optional[str]:
        query = (query or "").strip()
        if not query:
            return None
        for match in self._LOCATION_PATTERN.finditer(query):
            city = match.group("city")
            if not city:
                continue
            if city in self._INVALID_CITIES:
                continue
            if any(token in city for token in ["周", "星期", "今日", "明日", "后日"]):
                continue
            if any(token in city for token in self._AMBIGUOUS_CITY_TOKENS):
                continue
            normalized = city
            if not normalized.endswith("市"):
                normalized += "市"
            return normalized
        return None

    def _clean_query_for_location(self, query: str) -> str:
        cleaned = query
        for token in self._TIME_TOKENS_SORTED:
            cleaned = cleaned.replace(token, "")
        for pattern in self._DATE_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        return cleaned.strip()

    async def _extract_location_with_llm(self, query: str) -> Optional[LLMExtraction]:
        if not self._llm_enabled or not self._llm_client:
            return None
        system_prompt = (
            "你是地名和日期识别助手，请从用户的中文问题中识别最可能的城市、省份、国家以及目标日期。"
            "即使问题只提到是否下雨、刮风或气温变化，也要尽力判断可能的地点并返回最合理的猜测。"
            "必须严格返回 json 字段结构（json_object），如无把握可降低 confidence，但不要留空解释。"
        )
        payload = {
            "instruction": "从用户问题中提取最可能的地名以及目标日期，包括仅询问降雨、风力或气温的场景。",
            "query": query,
            "output_format": {
                "city": "中文地名或空字符串",
                "province": "若能判断的省份，否则空字符串",
                "country": "若能判断的国家，否则空字符串",
                "datetime": "ISO8601 日期或自然语言，如 '2025-10-27' 或 '这周日'",
                "confidence": "0~1 之间的小数，代表地名判断可信度",
            },
        }
        try:
            _, parsed = await self._llm_client.chat(
                system_prompt=system_prompt,
                messages=[
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather llm extract failed", error=str(exc))
            return None

        if not isinstance(parsed, dict):
            return None

        def _clean(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            return str(value).strip()

        city = _clean(parsed.get("city"))
        province = _clean(parsed.get("province"))
        country = _clean(parsed.get("country"))
        datetime_text = _clean(parsed.get("datetime") or parsed.get("date"))
        confidence_raw = parsed.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        return LLMExtraction(city, province, country, datetime_text, confidence)

    async def _extract_date_with_llm(self, query: str, base_time: datetime) -> Optional[LLMDateExtraction]:
        if not self._llm_enabled or not self._llm_client:
            return None
        system_prompt = (
            "你是中文自然语言日期解析助手。当前东八区时间为 "
            f"{base_time.isoformat()}。请理解用户的问题，将其中涉及的日期或相对时间换算为绝对日期。"
            "请务必输出 json_object，其中必须包含字段 resolved_date (格式为 YYYY-MM-DD)、"
            "confidence (0~1 浮点数) 和可选字段 reason。"
            "若无法确认，请返回空字符串并给出 reason。"
        )
        try:
            raw_text, parsed = await self._llm_client.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": query}],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather date llm extract failed", error=str(exc))
            return None

        if not isinstance(parsed, dict):
            logger.warning("weather date llm returned non-dict", raw=parsed)
            return None

        resolved_raw = parsed.get("resolved_date") or parsed.get("date") or ""
        resolved_str = str(resolved_raw).strip()
        if not resolved_str:
            return None
        resolved = self._coerce_date_string(resolved_str, base_time)
        if not resolved:
            logger.warning("weather date llm produced invalid date", value=resolved_str, raw_text=raw_text)
            return None
        confidence_raw = parsed.get("confidence", 1.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        reason = parsed.get("reason")
        if isinstance(reason, str):
            reason_text = reason.strip()
        else:
            reason_text = None
        logger.debug(
            "weather date resolved via llm",
            query=query,
            resolved_date=resolved.isoformat(),
            confidence=confidence,
            reason=reason_text,
        )
        return LLMDateExtraction(resolved, confidence, reason_text)

    def _coerce_date_string(self, text: str, base_time: datetime) -> Optional[date]:
        try:
            resolved_dt = datetime.fromisoformat(text)
            return resolved_dt.date()
        except ValueError:
            pass
        alt_parsed = parse_weather_date(text, base_time)
        if alt_parsed and alt_parsed.value:
            return alt_parsed.value.date()
        parsed_date = dateparser_parse(
            text,
            languages=["zh"],
            settings={
                "TIMEZONE": "Asia/Shanghai",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": base_time,
            },
        )
        if parsed_date:
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=base_time.tzinfo)
            return parsed_date.astimezone(base_time.tzinfo).date()
        return None

    def _normalize_city_name(self, raw: str) -> Optional[str]:
        name = (raw or "").strip()
        if not name:
            return None
        if any(token in name for token in self._AMBIGUOUS_CITY_TOKENS):
            return None
        if len(name) == 1:
            return None
        if name.endswith(("市", "区", "县", "州")):
            return name
        return name + "市"

    async def _resolve_point(self, location: Optional[str]) -> GeoPoint:
        if not location:
            return self._default_point
        normalized = location.strip()
        if normalized in _PRESET_GEO_POINTS:
            return _PRESET_GEO_POINTS[normalized]
        if normalized.endswith("市"):
            base = normalized[:-1]
            if base in _PRESET_GEO_POINTS:
                return _PRESET_GEO_POINTS[base]
        if location in self._geo_cache:
            return self._geo_cache[location]
        point = await self._geocode(location)
        if not point:
            return self._default_point
        self._geo_cache[location] = point
        normalized = location.strip()
        if normalized != location:
            self._geo_cache[normalized] = point
        return point

    async def _geocode(self, location: str) -> Optional[GeoPoint]:
        """
        使用 Nominatim 做轻量地理编码。

        说明：
        - 外部服务偶发超时/限流时，容易导致城市回退到默认坐标。
        - 这里通过“多候选 query + 更宽松超时”提升成功率；并保持总尝试次数很小，避免拖慢主链路。
        """
        url = "https://nominatim.openstreetmap.org/search"
        headers = {
            "User-Agent": "xy-assistant-weather/1.0",
            "Accept": "application/json",
        }

        normalized_name = location
        if normalized_name and not normalized_name.endswith("市") and len(normalized_name) <= 6:
            normalized_name += "市"

        query_candidates: list[str] = []
        location_raw = (location or "").strip()
        if location_raw:
            # 优先更精确的写法，减少首次查询超时导致的整体变慢。
            if not location_raw.endswith("市"):
                query_candidates.append(f"{location_raw}市")
            query_candidates.append(location_raw)
            # 增加“中国”前缀，提升命中概率（尤其是短地名）
            if not location_raw.startswith("中国"):
                if not location_raw.endswith("市"):
                    query_candidates.append(f"中国{location_raw}市")
                query_candidates.append(f"中国{location_raw}")

        # 单次请求严格控制超时，避免地理编码拖垮整体链路
        timeout = httpx.Timeout(3.0, connect=2.0)
        for candidate in query_candidates:
            params = {
                "format": "json",
                "limit": 1,
                "q": candidate,
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("geocode request failed", location=location, candidate=candidate, error=str(exc))
                continue

            if response.status_code != httpx.codes.OK:
                logger.warning("geocode http error", location=location, candidate=candidate, status=response.status_code)
                continue

            try:
                data = response.json()
            except ValueError:
                continue

            if not data:
                continue
            primary = data[0]
            try:
                lat = float(primary["lat"])
                lon = float(primary["lon"])
            except (KeyError, ValueError, TypeError):
                continue
            _ = primary.get("display_name")  # 仅用于调试时查看，不影响输出
            return GeoPoint(name=normalized_name or location, latitude=lat, longitude=lon)

        return None


def _parse_daily(body: Dict[str, Any]) -> list[WeatherDaily]:
    results: list[WeatherDaily] = []
    for key, value in body.items():
        if not key.startswith("f"):
            continue
        if not isinstance(value, dict) or "day" not in value:
            continue
        try:
            results.append(WeatherDaily.from_api(value))
        except Exception as exc:  # noqa: BLE001
            logger.debug("skip invalid weather day", key=key, error=str(exc))
    results.sort(key=lambda item: item.day)
    return results


def _describe_date(day_value: date, target: Optional[date]) -> str:
    today = now_e8().date()
    if day_value == today:
        return "今天"
    if day_value == today + timedelta(days=1):
        return "明天"
    if day_value == today + timedelta(days=2):
        return "后天"
    if target and day_value == target:
        return day_value.strftime("%m月%d日")
    return day_value.strftime("%m月%d日")
