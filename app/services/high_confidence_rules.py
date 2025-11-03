from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any, Dict, Optional

from loguru import logger

from app.schemas.response import FunctionAnalysis
from app.services.intent_definitions import IntentCode
from app.services.intent_rules import RuleResult, run_rules
from app.utils.time_utils import now_e8


NEGATIVE_TOKENS = {
    "不要",
    "别",
    "不想",
    "不需要",
    "不用",
    "先不要",
    "取消",
    "别帮",
    "别给",
}


WEATHER_INTENTS = {
    IntentCode.WEATHER_TODAY,
    IntentCode.WEATHER_TOMORROW,
    IntentCode.WEATHER_DAY_AFTER,
    IntentCode.WEATHER_SPECIFIC,
    IntentCode.WEATHER_OUT_OF_RANGE,
}

ACTIONABLE_INTENTS = WEATHER_INTENTS | {
    IntentCode.CALENDAR_GENERAL,
    IntentCode.TIME_BROADCAST,
    IntentCode.ALARM_CREATE,
    IntentCode.ALARM_REMINDER,
    IntentCode.ALARM_VIEW,
    IntentCode.SETTINGS_GENERAL,
    IntentCode.SETTINGS_SOUND_DOWN,
    IntentCode.SETTINGS_SOUND_UP,
    IntentCode.SETTINGS_BRIGHTNESS_DOWN,
    IntentCode.SETTINGS_BRIGHTNESS_UP,
    IntentCode.DEVICE_SCREEN_OFF,
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
    IntentCode.HEALTH_EVALUATION,
    IntentCode.HEALTH_PROFILE,
    IntentCode.HEALTH_DOCTOR_GENERAL,
    IntentCode.HEALTH_DOCTOR_SPECIFIC,
    IntentCode.HEALTH_SPECIALIST,
    IntentCode.MEDICATION_REMINDER_VIEW,
    IntentCode.MEDICATION_REMINDER_CREATE,
    IntentCode.FAMILY_DOCTOR_GENERAL,
    IntentCode.FAMILY_DOCTOR_CONTACT,
    IntentCode.FAMILY_DOCTOR_CALL_AUDIO,
    IntentCode.FAMILY_DOCTOR_CALL_VIDEO,
    IntentCode.ALBUM,
    IntentCode.COMMUNICATION_GENERAL,
    IntentCode.COMMUNICATION_CALL_AUDIO,
    IntentCode.COMMUNICATION_CALL_VIDEO,
    IntentCode.HOME_SERVICE_GENERAL,
    IntentCode.HOME_SERVICE_APPLIANCE,
    IntentCode.HOME_SERVICE_HOUSE,
    IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    IntentCode.HOME_SERVICE_MATERNAL,
    IntentCode.HOME_SERVICE_DOMESTIC,
    IntentCode.HOME_SERVICE_FOOT,
    IntentCode.EDUCATION_GENERAL,
    IntentCode.ENTERTAINMENT_GENERAL,
    IntentCode.ENTERTAINMENT_OPERA,
    IntentCode.ENTERTAINMENT_OPERA_SPECIFIC,
    IntentCode.ENTERTAINMENT_MUSIC,
    IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC,
    IntentCode.ENTERTAINMENT_AUDIOBOOK,
    IntentCode.ENTERTAINMENT_MUSIC_OFF,
    IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF,
    IntentCode.ENTERTAINMENT_OPERA_OFF,
    IntentCode.GAME_DOU_DI_ZHU,
    IntentCode.GAME_CHINESE_CHESS,
    IntentCode.CHAT,
    IntentCode.MALL_GENERAL,
    IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
    IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    IntentCode.MALL_SMART_LIFE_TERMINAL,
    IntentCode.MALL_HEALTH_FOOD,
    IntentCode.MALL_SILVER_PRODUCTS,
    IntentCode.MALL_DAILY_PRODUCTS,
    IntentCode.MALL_ORDERS,
}

MIN_CONFIDENCE = 0.96


@dataclass
class RuleMatch:
    analysis: FunctionAnalysis
    rule_result: RuleResult
    weather_detail: Optional[Dict[str, Any]] = None
    needs_realtime_weather: bool = False


class HighConfidenceRuleEngine:
    """高置信规则层：命中后可直接跳过 LLM 推理阶段。"""

    _CITY_SUFFIXES = ("市", "盟", "州", "县", "区", "旗", "自治州", "自治县", "自治区")
    _LOCATION_PATTERNS = [
        re.compile(r"(?:去|到|前往|准备去|赶去|要去|去往)(?P<city>[\u4e00-\u9fa5]{2,7})(?:市|省|自治区|县|区|州|旗)?"),
        re.compile(r"(?P<city>[\u4e00-\u9fa5]{2,7})(?:市|省|自治区|县|区|州|旗)?(?:这边|那边|当地|那里)?(?:的)?(?:天气|气温|气候|冷不冷|热不热|下雨|雨|晴)"),
    ]

    def __init__(self, default_city: str) -> None:
        self._default_city = default_city

    def evaluate(self, query: str, meta: Optional[Dict[str, Any]] = None) -> Optional[RuleMatch]:
        """返回高置信匹配结果，若不满足条件则返回 None。"""
        query = (query or "").strip()
        if not query:
            return None

        if any(token in query for token in NEGATIVE_TOKENS):
            return None

        rule_result = run_rules(query, meta or {})
        if not rule_result:
            return None

        if rule_result.intent_code not in ACTIONABLE_INTENTS:
            return None

        confidence = rule_result.confidence if rule_result.confidence is not None else MIN_CONFIDENCE
        confidence = max(confidence, MIN_CONFIDENCE)

        analysis = FunctionAnalysis(
            result=rule_result.result or "",
            target=rule_result.target or "",
            event=rule_result.event,
            status=rule_result.status,
            confidence=confidence,
            reasoning=rule_result.reasoning or "规则直接识别命中，可立即执行。",
            weather_condition=rule_result.weather_condition,
            need_clarify=False,
        )

        if rule_result.parsed_time:
            analysis.parsed_time = rule_result.parsed_time
        if rule_result.time_text:
            analysis.time_text = rule_result.time_text
        if rule_result.time_confidence is not None:
            analysis.time_confidence = rule_result.time_confidence
        if rule_result.time_source:
            analysis.time_source = rule_result.time_source

        if rule_result.intent_code in {IntentCode.ALARM_CREATE, IntentCode.ALARM_REMINDER}:
            if rule_result.target:
                analysis.parsed_time = rule_result.target
                analysis.time_source = "rule"

        if rule_result.intent_code == IntentCode.TIME_BROADCAST:
            current = now_e8()
            current_iso = current.strftime("%Y-%m-%d %H:%M:%S")
            analysis.target = current_iso
            analysis.parsed_time = current_iso
            analysis.time_text = "当前时间"
            analysis.time_source = "rule"
            analysis.reasoning = "规则识别报时功能，填入当前时间。"

        weather_detail: Optional[Dict[str, Any]] = None
        needs_realtime_weather = True

        if rule_result.intent_code in WEATHER_INTENTS:
            weather_detail = self._build_weather_detail(rule_result.intent_code, rule_result.target, query)
            needs_realtime_weather = weather_detail.get("needs_realtime_data", True) if weather_detail else True
            if rule_result.intent_code == IntentCode.WEATHER_OUT_OF_RANGE:
                # 远期天气无需实时接口
                needs_realtime_weather = False

        logger.debug(
            "high_confidence_rule_hit",
            intent=rule_result.intent_code.value,
            result=rule_result.result,
            target=rule_result.target,
        )

        return RuleMatch(
            analysis=analysis,
            rule_result=rule_result,
            weather_detail=weather_detail,
            needs_realtime_weather=needs_realtime_weather,
        )

    def _build_weather_detail(self, intent: IntentCode, target: Optional[str], query: str) -> Dict[str, Any]:
        """构造天气查询所需的简要结构，便于后续 WeatherService 拉取数据。"""
        base_time = now_e8()
        target_date: Optional[datetime] = None
        location_name = self._extract_location(query) or self._default_city

        if intent == IntentCode.WEATHER_TODAY:
            target_date = base_time
        elif intent == IntentCode.WEATHER_TOMORROW:
            target_date = base_time + timedelta(days=1)
        elif intent == IntentCode.WEATHER_DAY_AFTER:
            target_date = base_time + timedelta(days=2)
        elif intent == IntentCode.WEATHER_SPECIFIC and target:
            # target 格式 mmdd，需拼接年份
            try:
                month = int(target[:2])
                day = int(target[2:])
                year = base_time.year
                candidate = datetime(year, month, day)
                if candidate < base_time:
                    candidate = datetime(year + 1, month, day)
                target_date = candidate
            except (ValueError, TypeError):
                target_date = None

        detail: Dict[str, Any] = {
            "location": location_name,
            "location_confidence": 1.0,
            "needs_realtime_data": True,
        }
        if target_date:
            detail["target_date"] = target_date.strftime("%Y-%m-%d")
            detail["target_date_text"] = target_date.strftime("%Y-%m-%d")
            detail["target_date_confidence"] = 1.0
        return detail

    def _extract_location(self, query: str) -> Optional[str]:
        """尝试从语句中解析城市名称，不可判定时返回 None。"""
        if not query:
            return None
        cleaned = query.replace("去哪儿", "去哪里")
        for pattern in self._LOCATION_PATTERNS:
            match = pattern.search(cleaned)
            if not match:
                continue
            candidate = (match.group("city") or "").strip()
            if not candidate:
                continue
            candidate = re.sub(r"(今天|明天|后天|本周|这周|下周|上午|下午|晚上|夜里|今早|明早|后早|这边|那边|当地)", "", candidate)
            candidate = candidate.strip("的")
            if not candidate:
                continue
            candidate = re.split(r"(会|要|需|是否|是不是|冷|热|下雨|雨|适合|能否|可以|该)", candidate)[0]
            candidate = candidate.strip()
            # 避免时间词、泛指词
            if candidate in {"今天", "明天", "后天"}:
                continue
            if not candidate.endswith(self._CITY_SUFFIXES) and len(candidate) <= 5:
                candidate += "市"
            return candidate
        return None
