from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import dateparser
from zoneinfo import ZoneInfo

EAST_EIGHT = ZoneInfo("Asia/Shanghai")


# 人名净化列表：用于去除命令中的功能词，保留真实人名或称谓。
PERSON_NAME_STRIP_TOKENS = [
    "血压",
    "血氧",
    "心率",
    "血糖",
    "血脂",
    "体重",
    "体温",
    "血红蛋白",
    "尿酸",
    "睡眠",
    "监测",
    "提醒",
    "闹钟",
    "电话",
    "视频",
    "医生",
    "大夫",
    "老师",
    "服务",
    "计划",
    "联系",
    "预约",
    "设置",
    "打开",
    "查看",
    "小雅",
    "一下",
    "帮我",
    "给我",
    "的",
]


def sanitize_person_name(name: str) -> Optional[str]:
    """将识别到的人名剔除功能词后返回，若为空则返回 None。"""
    cleaned = name
    for token in PERSON_NAME_STRIP_TOKENS:
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.strip()
    # 限制长度，避免过长字段
    cleaned = cleaned[:8]
    return cleaned or None


@dataclass
class ParsedWeatherDate:
    """天气解析结果，kind 表示 today/tomorrow 或具体日期。"""
    kind: str
    value: Optional[datetime] = None


def now_e8() -> datetime:
    """返回东八区当前时间。"""
    return datetime.now(tz=EAST_EIGHT)


def parse_weather_date(text: str, base_time: Optional[datetime] = None) -> Optional[ParsedWeatherDate]:
    """解析用户文本中的日期关键词，返回日期类型与具体值。"""
    base_time = base_time or now_e8()
    text = text.strip()
    if "今天" in text:
        return ParsedWeatherDate("today", base_time)
    if "明天" in text:
        return ParsedWeatherDate("tomorrow", base_time + timedelta(days=1))
    if "后天" in text:
        return ParsedWeatherDate("day_after", base_time + timedelta(days=2))

    match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日?", text)
    if match:
        year = int(match.group(1)) if match.group(1) else base_time.year
        month = int(match.group(2))
        day = int(match.group(3))
        parsed_date = datetime(year=year, month=month, day=day, tzinfo=EAST_EIGHT)
        return ParsedWeatherDate("specific", parsed_date)

    return None


def is_within_days(target: datetime, base: datetime, days: int) -> bool:
    """判断目标日期是否位于指定天数以内。"""
    delta = target - base
    return 0 <= delta.days <= days


@dataclass
class TimeExpression:
    """时间匹配结果，支持绝对时间、相对时间及周期表达。"""
    datetime_value: Optional[datetime] = None
    relative_delta: Optional[timedelta] = None
    periodic_status: Optional[str] = None
    raw_text: Optional[str] = None


_relative_pattern = re.compile(
    r"(?:(?P<days>\d+)天)?(?:(?P<hours>\d+)小时)?(?:(?P<minutes>\d+)分钟)?后"
)

_periodic_pattern = re.compile(r"每周[一二三四五六日天]|每天|每日|每晚|每早")

_time_pattern = re.compile(r"(?:(上午|下午|早上|晚上|中午))?(\d{1,2})(点|点钟)(?:(\d{1,2})分)?")


_periodic_map = {
    "每天": "每天",
    "每日": "每日",
    "每早": "每天早上",
    "每晚": "每天晚上",
    "每周一": "每周一",
    "每周二": "每周二",
    "每周三": "每周三",
    "每周四": "每周四",
    "每周五": "每周五",
    "每周六": "每周六",
    "每周日": "每周日",
    "每周天": "每周日",
}


_meridiem_keywords = {
    "上午": "am",
    "早上": "am",
    "清晨": "am",
    "早": "am",
    "中午": "pm",
    "下午": "pm",
    "傍晚": "pm",
    "晚上": "pm",
    "晚": "pm",
}

_TIME_REPLACEMENTS = [
    ("明早上", "明天早上"),
    ("明早", "明天早上"),
    ("明天早晨", "明天早上"),
    ("明儿早上", "明天早上"),
    ("明儿", "明天"),
]


def _normalize_time_phrases(text: str) -> str:
    normalized = text
    for original, replacement in _TIME_REPLACEMENTS:
        normalized = normalized.replace(original, replacement)
    return normalized


def extract_time_expression(text: str, base_time: Optional[datetime] = None) -> Optional[TimeExpression]:
    """抽取文本中的时间表达（绝对时间 / 相对时间 / 周期描述）。"""
    base_time = base_time or now_e8()
    cleaned = _normalize_time_phrases(text.strip())
    expr = TimeExpression(raw_text=None)

    rel_match = _relative_pattern.search(cleaned)
    if rel_match:
        days = int(rel_match.group("days") or 0)
        hours = int(rel_match.group("hours") or 0)
        minutes = int(rel_match.group("minutes") or 0)
        expr.relative_delta = timedelta(days=days, hours=hours, minutes=minutes)
        expr.raw_text = rel_match.group(0)

    periodic_match = _periodic_pattern.search(cleaned)
    if periodic_match:
        periodic_text = periodic_match.group(0)
        expr.periodic_status = _periodic_map.get(periodic_text, periodic_text)
        expr.raw_text = periodic_text

    time_match = _time_pattern.search(cleaned)
    if time_match:
        meridiem = time_match.group(1) or ""
        hour = int(time_match.group(2))
        minute = int(time_match.group(4) or 0)
        resolved_hour = resolve_hour(hour, meridiem, base_time)
        candidate = base_time.replace(hour=resolved_hour, minute=minute, second=0, microsecond=0)
        if candidate <= base_time:
            candidate += timedelta(days=1)
        expr.datetime_value = candidate
        expr.raw_text = time_match.group(0)

    if not any([expr.relative_delta, expr.datetime_value, expr.periodic_status]):
        parsed = dateparser.parse(
            cleaned,
            languages=["zh"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": base_time,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": "Asia/Shanghai",
            },
        )
        if parsed:
            if not parsed.tzinfo:
                parsed = parsed.replace(tzinfo=EAST_EIGHT)
            expr.datetime_value = parsed
            expr.raw_text = cleaned

    if any([expr.relative_delta, expr.datetime_value, expr.periodic_status]):
        return expr
    return None


def resolve_hour(hour: int, meridiem: str, base_time: datetime) -> int:
    """根据上午/下午等语义调整小时值，并处理 6 点歧义。"""
    mer = _meridiem_keywords.get(meridiem, "")
    if mer == "am":
        return 0 if hour == 12 else hour
    if mer == "pm":
        return hour if hour >= 12 else hour + 12

    if hour == 6:
        if base_time.hour < 18:
            return 18
        return 6

    if hour <= base_time.hour:
        if hour < 12:
            return hour + 12
    return hour


def derive_alarm_target(
    query: str,
    base_time: datetime,
    time_expr: Optional[TimeExpression] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """格式化闹钟落地时间：返回 target（形如0d18h0m）、事件与频次。"""
    if not time_expr:
        return "", extract_event(query), None

    target = ""
    if time_expr.relative_delta:
        delta = time_expr.relative_delta
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        target = f"+{delta.days}d{hours}h{minutes}m"
    elif time_expr.datetime_value:
        dt = time_expr.datetime_value
        if dt <= base_time:
            dt += timedelta(days=1)
        day_offset = (dt.date() - base_time.date()).days
        target = f"{day_offset}d{dt.hour}h{dt.minute}m"

    status = time_expr.periodic_status
    event = extract_event(query)
    return target, event, status


def extract_event(text: str) -> Optional[str]:
    """从提醒语句中抽取事件关键词。"""
    cleaned = _normalize_time_phrases(text)
    cleaned = re.sub(r"提醒(我)?", "", cleaned)
    cleaned = re.sub(r"(闹钟|设定|设置|帮我|一下|一个|请|安排|订个?)", "", cleaned)
    cleaned = re.sub(_relative_pattern, "", cleaned)
    cleaned = re.sub(_time_pattern, "", cleaned)
    cleaned = cleaned.replace("每周", "").replace("每天", "")
    cleaned = cleaned.replace("明天", "").replace("明早", "")
    cleaned = re.sub(r"的$", "", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def extract_person_name(text: str) -> Optional[str]:
    """通过常见句式提取人名，用于通话/健康等功能。"""
    patterns = [
        r"给(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})",
        r"联系(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})",
        r"找(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})",
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})医生",
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})大夫",
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,8})的",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group("name")
            sanitized = sanitize_person_name(candidate)
            if sanitized:
                return sanitized
    return None


def extract_medicine(text: str) -> Optional[str]:
    """识别用药计划中的药品名称。"""
    match = re.search(r"每天吃(?P<name>[\u4e00-\u9fa5A-Za-z0-9]+)", text)
    if match:
        return match.group("name")
    match = re.search(r"吃(?P<name>[\u4e00-\u9fa5A-Za-z0-9]+)", text)
    if match:
        return match.group("name")
    return None


def describe_alarm_target(target: str, base_time: Optional[datetime] = None) -> str:
    """将闹钟 target（0d18h0m / +0d0h10m）转换为易读的中文描述。"""
    if not target:
        return "指定时间"

    base_time = base_time or now_e8()
    absolute_pattern = re.compile(r"(?P<days>\d+)d(?P<hours>\d+)h(?P<minutes>\d+)m")
    relative_pattern = re.compile(r"\+(?P<days>\d+)d(?P<hours>\d+)h(?P<minutes>\d+)m")

    if relative_match := relative_pattern.fullmatch(target):
        days = int(relative_match.group("days"))
        hours = int(relative_match.group("hours"))
        minutes = int(relative_match.group("minutes"))
        parts: list[str] = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        if not parts:
            parts.append("0分钟")
        return "".join(parts) + "后"

    absolute_match = absolute_pattern.fullmatch(target)
    if not absolute_match:
        return target

    day_offset = int(absolute_match.group("days"))
    hour = int(absolute_match.group("hours"))
    minute = int(absolute_match.group("minutes"))

    target_time = base_time + timedelta(days=day_offset)
    target_time = target_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if day_offset == 0:
        day_text = "今天"
    elif day_offset == 1:
        day_text = "明天"
    elif day_offset == 2:
        day_text = "后天"
    else:
        day_text = target_time.strftime("%m月%d日")

    time_text = target_time.strftime("%H:%M")
    return f"{day_text}{time_text}"
