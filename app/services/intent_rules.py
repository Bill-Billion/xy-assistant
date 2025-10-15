from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from app.services.intent_definitions import IntentCode, INTENT_DEFINITIONS
from app.utils.calendar_utils import format_lunar_summary, get_lunar_info
from app.utils.time_utils import (
    derive_alarm_target,
    extract_person_name,
    extract_time_expression,
    is_within_days,
    now_e8,
    parse_weather_date,
    extract_medicine,
)


@dataclass
class RuleContext:
    query: str
    meta: dict[str, Any]
    base_time: datetime


@dataclass
class RuleResult:
    intent_code: IntentCode
    result: str
    target: Optional[str] = None
    event: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[float] = None
    need_clarify: bool = False
    clarify_message: Optional[str] = None
    reasoning: Optional[str] = None


# 健康监测关键词映射：不同检测需求需返回对应细分意图与固定 result。
_health_metric_map = {
    "血压": (IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE, "血压监测"),
    "测血压": (IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE, "血压监测"),
    "血压监测": (IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE, "血压监测"),
    "血氧": (IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN, "血氧监测"),
    "血氧监测": (IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN, "血氧监测"),
    "心率": (IntentCode.HEALTH_MONITOR_HEART_RATE, "心率监测"),
    "心率监测": (IntentCode.HEALTH_MONITOR_HEART_RATE, "心率监测"),
    "血糖": (IntentCode.HEALTH_MONITOR_BLOOD_SUGAR, "血糖监测"),
    "血糖监测": (IntentCode.HEALTH_MONITOR_BLOOD_SUGAR, "血糖监测"),
    "血脂": (IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS, "血脂监测"),
    "血脂监测": (IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS, "血脂监测"),
    "体重": (IntentCode.HEALTH_MONITOR_WEIGHT, "体重监测"),
    "称体重": (IntentCode.HEALTH_MONITOR_WEIGHT, "体重监测"),
    "体温": (IntentCode.HEALTH_MONITOR_BODY_TEMPERATURE, "体温监测"),
    "测体温": (IntentCode.HEALTH_MONITOR_BODY_TEMPERATURE, "体温监测"),
    "血红蛋白": (IntentCode.HEALTH_MONITOR_HEMOGLOBIN, "血红蛋白监测"),
    "尿酸": (IntentCode.HEALTH_MONITOR_URIC_ACID, "尿酸监测"),
    "睡眠": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
    "睡眠监测": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
}


def apply_weather_rule(context: RuleContext) -> Optional[RuleResult]:
    """天气相关意图匹配，优先识别今天/明天/后天，或处理指定日期。"""
    weather_match = re.search(r"天气", context.query)
    if not weather_match:
        return None

    parsed = parse_weather_date(context.query, context.base_time)
    if not parsed:
        return None

    date_kind, date_value = parsed.kind, parsed.value
    if date_kind == "today":
        return RuleResult(IntentCode.WEATHER_TODAY, "今天天气", target="今天")
    if date_kind == "tomorrow":
        return RuleResult(IntentCode.WEATHER_TOMORROW, "明天天气", target="明天")
    if date_kind == "day_after":
        return RuleResult(IntentCode.WEATHER_DAY_AFTER, "后天天气", target="后天")
    if date_kind == "specific":
        if not is_within_days(date_value, context.base_time, 15):
            return RuleResult(IntentCode.WEATHER_OUT_OF_RANGE, "我还只能查到15天内的天气哦", target="")
        return RuleResult(IntentCode.WEATHER_SPECIFIC, f"{date_value.strftime('%m%d')}天气", target=date_value.strftime("%m%d"))
    return None


def apply_calendar_rule(context: RuleContext) -> Optional[RuleResult]:
    """处理日历、黄历、吉日等需求。"""
    terms = ["几月几日", "农历", "黄历", "黄道吉日", "节气", "日期", "几号", "万年历", "适合搬家", "宜搬家", "搬家吉日"]
    if any(term in context.query for term in terms) or ("适合" in context.query and "搬家" in context.query):
        lunar = get_lunar_info(context.base_time)
        summary = format_lunar_summary(lunar) if lunar else None
        reasoning = f"提供日期及万年历信息，包含：{summary}" if summary else "提供日期及万年历信息"
        return RuleResult(IntentCode.CALENDAR_GENERAL, "日期时间和万年历", reasoning=reasoning)
    return None


def apply_time_rule(context: RuleContext) -> Optional[RuleResult]:
    """时间播报与闹钟提醒解析。"""
    if "几点" in context.query or "现在时间" in context.query:
        return RuleResult(IntentCode.TIME_BROADCAST, "播报时间")
    if "闹钟" in context.query:
        if any(token in context.query for token in ["打开", "查看", "进入"]):
            return RuleResult(IntentCode.ALARM_VIEW, "闹钟界面", target="")
        time_expr = extract_time_expression(context.query, context.base_time)
        if not time_expr:
            return RuleResult(IntentCode.ALARM_CREATE, "新增闹钟", target="")
        target_str, event, status = derive_alarm_target(context.query, context.base_time, time_expr)
        return RuleResult(IntentCode.ALARM_CREATE, "新增闹钟", target=target_str, event=event, status=status)
    if "提醒" in context.query:
        time_expr = extract_time_expression(context.query, context.base_time)
        target_str, event, status = derive_alarm_target(context.query, context.base_time, time_expr)
        return RuleResult(IntentCode.ALARM_REMINDER, "新增闹钟", target=target_str, event=event, status=status)
    return None


def apply_settings_rule(context: RuleContext) -> Optional[RuleResult]:
    """系统设置相关指令（声音/亮度等）。"""
    q = context.query
    if "设置" in q:
        return RuleResult(IntentCode.SETTINGS_GENERAL, "小雅设置")
    if "声音" in q:
        if "低" in q or "小" in q or "减" in q:
            return RuleResult(IntentCode.SETTINGS_SOUND_DOWN, "声音调低")
        if "高" in q or "大" in q or "增" in q:
            return RuleResult(IntentCode.SETTINGS_SOUND_UP, "声音调高")
    if "亮度" in q:
        if any(token in q for token in ["低", "暗", "减"]):
            return RuleResult(IntentCode.SETTINGS_BRIGHTNESS_DOWN, "亮度调低")
        if any(token in q for token in ["高", "亮", "增"]):
            return RuleResult(IntentCode.SETTINGS_BRIGHTNESS_UP, "亮度调高")
    return None


def apply_health_rules(context: RuleContext) -> Optional[RuleResult]:
    """健康领域指令匹配，覆盖监测、评估、医生咨询等。"""
    q = context.query
    if "健康监测" in q or "健康检测" in q:
        return RuleResult(IntentCode.HEALTH_MONITOR_GENERAL, "健康监测")
    for metric, (intent_code, result_text) in _health_metric_map.items():
        if metric in q:
            person = extract_person_name(q)
            return RuleResult(intent_code, result_text, target=person or "", confidence=0.95)
    if "健康评估" in q:
        person = extract_person_name(q)
        return RuleResult(IntentCode.HEALTH_EVALUATION, "健康评估", target=person or "")
    if "健康科普" in q or "科普" in q:
        return RuleResult(IntentCode.HEALTH_EDUCATION, "健康科普")
    if "健康画像" in q:
        person = extract_person_name(q)
        return RuleResult(IntentCode.HEALTH_PROFILE, "健康画像", target=person or "")
    if "小雅医生" in q or "健康咨询" in q:
        person = extract_person_name(q)
        if person:
            return RuleResult(IntentCode.HEALTH_DOCTOR_SPECIFIC, "小雅医生", target=person)
        return RuleResult(IntentCode.HEALTH_DOCTOR_GENERAL, "小雅医生")
    if "名医问诊" in q or "远程问诊" in q:
        return RuleResult(IntentCode.HEALTH_SPECIALIST, "名医问诊")
    if "用药提醒" in q or "服药计划" in q:
        person = extract_person_name(q)
        return RuleResult(IntentCode.MEDICATION_REMINDER_VIEW, "用药提醒", target=person or "")
    if "新增" in q and ("用药" in q or "服药" in q):
        medicine = extract_medicine(q)
        return RuleResult(IntentCode.MEDICATION_REMINDER_CREATE, "新建用药提醒", target=medicine or "")
    return None


def extract_doctor_name(text: str) -> Optional[str]:
    """提取“XX医生/大夫”完整称呼，便于作为 target 返回。"""
    match = re.search(r'(?:联系|找|帮我|给)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(医生|大夫)', text)
    if match:
        base = match.group('name')
        suffix = match.group(2)
        return f"{base}{suffix}"
    return None


def apply_family_doctor_rule(context: RuleContext) -> Optional[RuleResult]:
    """识别家庭医生服务，包括指定医生音视频通话。"""
    q = context.query
    doctor_name_full = extract_doctor_name(q)

    if "家庭医生" in q:
        person = extract_person_name(q)
        if "视频" in q:
            return RuleResult(IntentCode.FAMILY_DOCTOR_CALL_VIDEO, "家庭医生视频通话", target=person or "")
        if any(token in q for token in ["电话", "打个电话", "拨打", "联系"]):
            return RuleResult(IntentCode.FAMILY_DOCTOR_CALL_AUDIO, "家庭医生音频通话", target=person or "")
        if person:
            return RuleResult(IntentCode.FAMILY_DOCTOR_CONTACT, "家庭医生", target=person)
        return RuleResult(IntentCode.FAMILY_DOCTOR_GENERAL, "家庭医生")

    if doctor_name_full:
        if "视频" in q or "视频通话" in q:
            return RuleResult(IntentCode.FAMILY_DOCTOR_CALL_VIDEO, "家庭医生视频通话", target=doctor_name_full, confidence=0.9)
        if any(token in q for token in ["电话", "打电话", "拨打", "联系"]):
            return RuleResult(IntentCode.FAMILY_DOCTOR_CALL_AUDIO, "家庭医生音频通话", target=doctor_name_full, confidence=0.9)
        return RuleResult(IntentCode.FAMILY_DOCTOR_CONTACT, "家庭医生", target=doctor_name_full, confidence=0.85)

    return None


def apply_album_rule(context: RuleContext) -> Optional[RuleResult]:
    if "相册" in context.query or "照片" in context.query:
        return RuleResult(IntentCode.ALBUM, "小雅相册")
    return None


def apply_communication_rule(context: RuleContext) -> Optional[RuleResult]:
    q = context.query
    if any(term in q for term in ["联系家人", "跟家人", "小雅通话"]):
        return RuleResult(IntentCode.COMMUNICATION_GENERAL, "小雅通话")
    if "打电话" in q or "打个电话" in q:
        person = extract_person_name(q)
        return RuleResult(IntentCode.COMMUNICATION_CALL_AUDIO, "小雅音频通话", target=person or "")
    if "打视频" in q or "视频" in q:
        person = extract_person_name(q)
        return RuleResult(IntentCode.COMMUNICATION_CALL_VIDEO, "小雅视频通话", target=person or "")
    return None


_home_service_map = {
    "家政": IntentCode.HOME_SERVICE_DOMESTIC,
    "保洁": IntentCode.HOME_SERVICE_DOMESTIC,
    "阿姨": IntentCode.HOME_SERVICE_DOMESTIC,
    "家政服务": IntentCode.HOME_SERVICE_DOMESTIC,
    "家电": IntentCode.HOME_SERVICE_APPLIANCE,
    "电器": IntentCode.HOME_SERVICE_APPLIANCE,
    "电视": IntentCode.HOME_SERVICE_APPLIANCE,
    "冰箱": IntentCode.HOME_SERVICE_APPLIANCE,
    "空调": IntentCode.HOME_SERVICE_APPLIANCE,
    "房屋": IntentCode.HOME_SERVICE_HOUSE,
    "墙": IntentCode.HOME_SERVICE_HOUSE,
    "屋顶": IntentCode.HOME_SERVICE_HOUSE,
    "漏水": IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    "水管": IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    "电": IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    "线路": IntentCode.HOME_SERVICE_WATER_ELECTRIC,
    "母婴": IntentCode.HOME_SERVICE_MATERNAL,
    "月嫂": IntentCode.HOME_SERVICE_MATERNAL,
    "足道": IntentCode.HOME_SERVICE_FOOT,
    "足疗": IntentCode.HOME_SERVICE_FOOT,
}


def apply_home_service_rule(context: RuleContext) -> Optional[RuleResult]:
    q = context.query
    if "小雅家政" in q or "预约服务" in q or "服务预约" in q:
        return RuleResult(IntentCode.HOME_SERVICE_GENERAL, "小雅家政")
    for keyword, code in _home_service_map.items():
        if keyword in q:
            return RuleResult(code, INTENT_DEFINITIONS[code].result)
    return None


def apply_education_rule(context: RuleContext) -> Optional[RuleResult]:
    if ("学习" in context.query or "课程" in context.query or "教学" in context.query or
            re.search(r"(想|要|帮我).{0,2}学[\u4e00-\u9fa5A-Za-z0-9]{1,}", context.query)):
        subject = extract_subject(context.query)
        return RuleResult(IntentCode.EDUCATION_GENERAL, "小雅教育", target=subject or "")
    return None


def apply_entertainment_rule(context: RuleContext) -> Optional[RuleResult]:
    q = context.query
    if any(term in q for term in ["娱乐", "玩", "游戏"]):
        if "斗地主" in q:
            return RuleResult(IntentCode.GAME_DOU_DI_ZHU, "斗地主")
        if "象棋" in q:
            return RuleResult(IntentCode.GAME_CHINESE_CHESS, "中国象棋")
        return RuleResult(IntentCode.ENTERTAINMENT_GENERAL, "娱乐")
    if "戏曲" in q or "听戏" in q or "曲艺" in q:
        title = extract_subject(q)
        if title and len(title) > 1:
            return RuleResult(IntentCode.ENTERTAINMENT_OPERA_SPECIFIC, "小雅曲艺", target=title)
        return RuleResult(IntentCode.ENTERTAINMENT_OPERA, "小雅曲艺")
    if "音乐" in q or "听歌" in q:
        title = extract_subject(q)
        if title:
            return RuleResult(IntentCode.ENTERTAINMENT_MUSIC_SPECIFIC, "小雅音乐", target=title)
        return RuleResult(IntentCode.ENTERTAINMENT_MUSIC, "小雅音乐")
    if "听书" in q or "听小说" in q:
        return RuleResult(IntentCode.ENTERTAINMENT_AUDIOBOOK, "小雅听书")
    if any(term in q for term in ["聊天", "陪我聊", "聊聊"]):
        return RuleResult(IntentCode.CHAT, "语音陪伴或聊天")
    return None


_mall_keywords_map = {
    "小雅商城": IntentCode.MALL_GENERAL,
    "购买商品": IntentCode.MALL_GENERAL,
    "数字健康机器人": IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
    "健康机器人": IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
    "机器人": IntentCode.MALL_DIGITAL_HEALTH_ROBOT,
    "健康监测终端": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "监测终端": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "监测设备": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "监测设备": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "血压计": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "血氧仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "血糖仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "血脂仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "体重秤": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "温度计": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "尿酸检测仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "血红蛋白检测仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "睡眠监测仪": IntentCode.MALL_HEALTH_MONITOR_TERMINAL,
    "智慧生活终端": IntentCode.MALL_SMART_LIFE_TERMINAL,
    "健康食疗产品": IntentCode.MALL_HEALTH_FOOD,
    "适老化用品": IntentCode.MALL_SILVER_PRODUCTS,
    "日常生活用品": IntentCode.MALL_DAILY_PRODUCTS,
    "我的订单": IntentCode.MALL_ORDERS,
    "查看订单": IntentCode.MALL_ORDERS,
}


def apply_mall_rule(context: RuleContext) -> Optional[RuleResult]:
    q = context.query
    for keyword, code in _mall_keywords_map.items():
        if keyword in q:
            return RuleResult(code, INTENT_DEFINITIONS[code].result)
    if "商城" in q or "购买" in q:
        return RuleResult(IntentCode.MALL_GENERAL, "商城")
    return None


RULE_CHAIN = [
    apply_weather_rule,
    apply_calendar_rule,
    apply_time_rule,
    apply_settings_rule,
    apply_health_rules,
    apply_family_doctor_rule,
    apply_album_rule,
    apply_communication_rule,
    apply_home_service_rule,
    apply_education_rule,
    apply_entertainment_rule,
    apply_mall_rule,
]


def run_rules(query: str, meta: dict[str, Any] | None = None) -> Optional[RuleResult]:
    meta = meta or {}
    context = RuleContext(query=query, meta=meta, base_time=now_e8())
    for rule in RULE_CHAIN:
        try:
            result = rule(context)
            if result:
                logger.debug("rule matched", rule=rule.__name__, result=result)
                return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("rule error", rule=rule.__name__, error=str(exc))
    return None


def extract_subject(text: str) -> Optional[str]:
    match = re.search(r"学([\u4e00-\u9fa5A-Za-z0-9]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"听([\u4e00-\u9fa5A-Za-z0-9]{2,})", text)
    if match:
        return match.group(1)
    return None
