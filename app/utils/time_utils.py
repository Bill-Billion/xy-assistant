from __future__ import annotations

import re
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

try:
    import cn2an
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    cn2an = None

import dateparser
from zoneinfo import ZoneInfo

EAST_EIGHT = ZoneInfo("Asia/Shanghai")

_DATE_LABEL_PATTERNS = [
    r"今天",
    r"明天",
    r"后天",
    r"大后天",
    r"下+周[一二三四五六日天1234567]",
    r"这周[一二三四五六日天1234567]",
    r"本周[一二三四五六日天1234567]",
    r"下+星期[一二三四五六日天1234567]",
    r"这星期[一二三四五六日天1234567]",
    r"本星期[一二三四五六日天1234567]",
    r"下+礼拜[一二三四五六日天1234567]",
    r"这礼拜[一二三四五六日天1234567]",
    r"本礼拜[一二三四五六日天1234567]",
    r"\d{1,2}月\d{1,2}日?",
    r"\d{1,2}号",
]

_WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
    "6": 5,
    "7": 6,
}

_WEEK_PREFIX_PATTERN = re.compile(r"(?P<prefix>下+|这|本)?(?:周|星期|礼拜)(?P<day>[一二三四五六日天1234567])")
_RELATIVE_DAY_PATTERN = re.compile(r"(?P<num>[零〇一二三四五六七八九十百千万两兩\d]+)天后")
_LUNAR_SPECIFIC_PATTERN = re.compile(
    r"农历(?P<leap>闰)?(?P<month>[正冬腊一二三四五六七八九十0-9两兩]+)月(?P<day>[初十廿卅三十二一二三四五六七八九十0-9两兩]+)"
)

_SPECIAL_MONTH_MAP = {
    "正": 1,
    "腊": 12,
    "冬": 11,
}


# 人名净化列表：用于去除命令中的功能词，保留真实人名或称谓。
PERSON_NAME_STRIP_TOKENS = [
    "小雅",
    "一下",
    "一下下",
    "请",
    "麻烦",
    "帮我",
    "给我",
    "我想",
    "我想要",
    "我需要",
    "想给",
    "想要",
    "想请",
]

PERSON_NAME_SUFFIX_TOKENS = [
    "医生",
    "大夫",
    "老师",
    "师傅",
    "主任",
    "护士",
]

PERSON_NAME_MEASURE_SUFFIX_PATTERN = re.compile(
    r"(测量|量血压|测血压|量血糖|测血糖|量血脂|测血脂|量血|测血|测体温|量体温|监测|检测|检查|测|量)$"
)

PERSON_NAME_LEADING_TOKENS = [
    "看一下",
    "看看",
    "查看",
    "看",
    "打开",
    "我要",
    "我想",
    "帮我",
    "想给",
    "想为",
    "想帮",
]


def sanitize_person_name(name: str) -> Optional[str]:
    """将识别到的人名剔除功能词后返回，若为空则返回 None。"""
    if not name:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    for token in PERSON_NAME_LEADING_TOKENS:
        if cleaned.startswith(token):
            cleaned = cleaned[len(token):].strip()
    for token in PERSON_NAME_STRIP_TOKENS:
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.strip()
    if cleaned.endswith("的"):
        cleaned = cleaned[:-1].strip()
    for suffix in PERSON_NAME_SUFFIX_TOKENS:
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    cleaned = PERSON_NAME_MEASURE_SUFFIX_PATTERN.sub("", cleaned).strip()
    # 限制长度，避免过长字段
    cleaned = cleaned[:8]
    if cleaned in {"", "我", "你", "他", "她", "它"}:
        return None
    return cleaned or None


@dataclass
class ParsedWeatherDate:
    """天气解析结果，kind 表示 today/tomorrow 或具体日期，phrase 保留原始描述。"""
    kind: str
    value: Optional[datetime] = None
    phrase: Optional[str] = None


def now_e8() -> datetime:
    """返回东八区当前时间。"""
    return datetime.now(tz=EAST_EIGHT)


def parse_weather_date(text: str, base_time: Optional[datetime] = None) -> Optional[ParsedWeatherDate]:
    """解析用户文本中的日期关键词，返回日期类型与具体值。"""
    base_time = (base_time or now_e8()).astimezone(EAST_EIGHT)
    text = text.strip()
    if "今天" in text:
        return ParsedWeatherDate("today", base_time, phrase="今天")
    if "明天" in text and "天后" not in text:
        return ParsedWeatherDate("tomorrow", base_time + timedelta(days=1), phrase="明天")
    if "后天" in text and "天后" not in text:
        return ParsedWeatherDate("day_after", base_time + timedelta(days=2), phrase="后天")
    if "大后天" in text:
        return ParsedWeatherDate("specific", base_time + timedelta(days=3), phrase="大后天")

    if relative := _extract_relative_days(text, base_time):
        return relative
    if weekday_date := _extract_weekday_date(text, base_time):
        return weekday_date

    match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日?", text)
    if match:
        year = int(match.group(1)) if match.group(1) else base_time.year
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            parsed_date = datetime(year=year, month=month, day=day, tzinfo=EAST_EIGHT)
        except ValueError:
            return None
        return ParsedWeatherDate("specific", parsed_date, phrase=match.group(0))

    parsed = dateparser.parse(
        text,
        languages=["zh"],
        settings={
            "RELATIVE_BASE": base_time,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Asia/Shanghai",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if parsed:
        parsed = parsed.astimezone(EAST_EIGHT)
        phrase = _extract_date_phrase(text) or text
        return ParsedWeatherDate("specific", parsed.replace(hour=0, minute=0, second=0, microsecond=0), phrase=phrase)

    return None


def _extract_date_phrase(text: str) -> Optional[str]:
    for pattern in _DATE_LABEL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _parse_numeric_text(raw: str) -> Optional[int]:
    raw = raw.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if cn2an is not None:
        try:
            return int(cn2an.cn2an(raw, "smart"))
        except (ValueError, TypeError):
            return None
    return None


def _resolve_weekday(base_time: datetime, weekday_index: int, offset_weeks: int, same_week_keyword: bool) -> datetime:
    monday = base_time - timedelta(days=base_time.weekday())
    candidate = monday + timedelta(days=weekday_index + offset_weeks * 7)
    if same_week_keyword and candidate.date() < base_time.date():
        candidate += timedelta(days=7)
    return candidate


def _extract_weekday_date(text: str, base_time: datetime) -> Optional[ParsedWeatherDate]:
    match = _WEEK_PREFIX_PATTERN.search(text)
    if not match:
        return None
    day_token = match.group("day")
    if day_token not in _WEEKDAY_MAP:
        return None
    prefix = match.group("prefix") or ""
    weekday_index = _WEEKDAY_MAP[day_token]
    offset_weeks = 0
    same_week_keyword = prefix in {"", "这", "本"}
    if prefix.startswith("下"):
        offset_weeks = len(prefix)
    candidate = _resolve_weekday(base_time, weekday_index, offset_weeks if prefix.startswith("下") else 0, same_week_keyword)
    return ParsedWeatherDate(kind="specific", value=candidate.replace(hour=0, minute=0, second=0, microsecond=0), phrase=match.group(0))


def _extract_relative_days(text: str, base_time: datetime) -> Optional[ParsedWeatherDate]:
    match = _RELATIVE_DAY_PATTERN.search(text)
    if not match:
        return None
    num_raw = match.group("num")
    days = _parse_numeric_text(num_raw)
    if days is None:
        return None
    candidate = base_time + timedelta(days=days)
    return ParsedWeatherDate(kind="specific", value=candidate.replace(hour=0, minute=0, second=0, microsecond=0), phrase=match.group(0))


def _convert_lunar_month(month_text: str) -> Optional[int]:
    text = month_text.replace("农历", "").replace("月", "").replace("闰", "").strip()
    if not text:
        return None
    if text in _SPECIAL_MONTH_MAP:
        return _SPECIAL_MONTH_MAP[text]
    if text.isdigit():
        value = int(text)
        return value if 1 <= value <= 12 else None
    # 处理十月、十一、十二
    replacements = {
        "十": 10,
        "十 一": 11,
        "十一": 11,
        "十 二": 12,
        "十二": 12,
    }
    if text in replacements:
        return replacements[text]
    if cn2an is not None:
        try:
            value = int(cn2an.cn2an(text, "smart"))
            return value if 1 <= value <= 12 else None
        except (ValueError, TypeError):
            return None
    return None


def _convert_lunar_day(day_text: str) -> Optional[int]:
    text = day_text.replace("日", "").replace("号", "").strip()
    if not text:
        return None
    if text.startswith("初"):
        base = _parse_numeric_text(text[1:])
        return base if base is not None else None
    if text.startswith("廿"):
        if text == "廿":
            return 20
        rest = text[1:]
        value = _parse_numeric_text(rest)
        if value is None:
            return None
        return 20 + value
    if text.startswith("卅") or text == "三十":
        if text in {"卅", "三十"}:
            return 30
        rest = text[1:]
        value = _parse_numeric_text(rest)
        if value is None:
            return None
        return 30 + value
    if text in {"二十", "二十"}:
        return 20
    if text in {"二十一", "二十 一"}:
        return 21
    if text in {"二十二", "二十 二"}:
        return 22
    if text in {"二十三", "二十 三"}:
        return 23
    if text in {"二十四", "二十 四"}:
        return 24
    if text in {"二十五", "二十 五"}:
        return 25
    if text in {"二十六", "二十 六"}:
        return 26
    if text in {"二十七", "二十 七"}:
        return 27
    if text in {"二十八", "二十 八"}:
        return 28
    if text in {"二十九", "二十 九"}:
        return 29
    if text in {"三十一", "三十 一"}:
        return 31
    if cn2an is not None:
        try:
            value = int(cn2an.cn2an(text, "smart"))
            return value if 1 <= value <= 30 else None
        except (ValueError, TypeError):
            return None
    return None


def parse_lunar_request(text: str, base_time: Optional[datetime] = None) -> Optional[Tuple[datetime, str]]:
    match = _LUNAR_SPECIFIC_PATTERN.search(text)
    if not match:
        return None

    month = _convert_lunar_month(match.group("month"))
    day = _convert_lunar_day(match.group("day"))
    is_leap = bool(match.group("leap"))
    if month is None or day is None:
        return None

    base = (base_time or now_e8()).astimezone(EAST_EIGHT)
    for offset in range(0, 730):
        candidate = base + timedelta(days=offset)
        solar = Solar.fromYmd(candidate.year, candidate.month, candidate.day)
        lunar = solar.getLunar()
        try:
            lunar_month = lunar.getMonth()
            lunar_day = lunar.getDay()
            leap_flag = False
            if hasattr(lunar, "isLeap"):
                leap_flag = lunar.isLeap()
            elif hasattr(lunar, "isLeapMonth"):
                leap_flag = lunar.isLeapMonth()
            if lunar_month < 0:
                lunar_month = abs(lunar_month)
                leap_flag = True
        except AttributeError:
            lunar_month_text = lunar.getMonthInChinese()
            lunar_day_text = lunar.getDayInChinese()
            leap_flag = "闰" in lunar_month_text
            lunar_month = _convert_lunar_month(lunar_month_text)
            lunar_day = _convert_lunar_day(lunar_day_text)
        if lunar_month is None or lunar_day is None:
            continue
        if lunar_month == month and lunar_day == day:
            if is_leap and not leap_flag:
                continue
            if not is_leap and leap_flag:
                continue
            return candidate.replace(hour=0, minute=0, second=0, microsecond=0), match.group(0)
    return None


def resolve_calendar_target(
    text: str,
    base_time: Optional[datetime] = None,
) -> Tuple[datetime, str]:
    """为日历/农历查询确定目标日期及描述文本。"""
    lunar_result = parse_lunar_request(text, base_time)
    if lunar_result:
        target_dt, label = lunar_result
        return target_dt, label
    base_time = (base_time or now_e8()).astimezone(EAST_EIGHT)
    weather_date = parse_weather_date(text, base_time)
    if weather_date and weather_date.value:
        target = weather_date.value.astimezone(EAST_EIGHT)
        label_map = {
            "today": "今天",
            "tomorrow": "明天",
            "day_after": "后天",
        }
        label = label_map.get(weather_date.kind)
        if weather_date.kind == "specific":
            label = weather_date.phrase or target.strftime("%m月%d日")
        if not label:
            label = weather_date.phrase or _extract_date_phrase(text) or target.strftime("%Y年%m月%d日")
        return target, label

    parsed = dateparser.parse(
        text,
        languages=["zh"],
        settings={
            "RELATIVE_BASE": base_time,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "Asia/Shanghai",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if parsed:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=EAST_EIGHT)
        else:
            parsed = parsed.astimezone(EAST_EIGHT)
        label = _extract_date_phrase(text) or parsed.strftime("%Y年%m月%d日")
        return parsed, label

    label = _extract_date_phrase(text) or "今天"
    return base_time, label


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
    date_value: Optional[datetime] = None
    is_date_only: bool = False


_relative_pattern = re.compile(
    r"(?:(?P<days>\d+(?:\.\d+)?)(?:天|日))?"
    r"(?:(?P<hours>\d+(?:\.\d+)?)(?:小时|个小时|时))?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)(?:分钟|分))?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)(?:秒钟?|秒))?"
    r"(?:后)?"
)

_periodic_pattern = re.compile(r"每周[一二三四五六日天]|每天|每日|每晚|每早")

_time_pattern = re.compile(r"(?:(上午|下午|早上|晚上|中午))?(\d{1,2})(点|点钟)(?:(\d{1,2})分)?")
_date_pattern = re.compile(r"(?:(\d{2,4})年)?(\d{1,2})月(\d{1,2})(?:日|号)?")


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

_TIME_SUFFIX_MAP = {
    "之后": "后",
    "过后": "后",
    "以后": "后",
    "过一会儿": "后",
}

_HALF_PATTERNS = [
    (re.compile(r"([零〇一二三四五六七八九十百千万两兩\d]+)个?小时半"), "小时"),
    (re.compile(r"([零〇一二三四五六七八九十百千万两兩\d]+)个?天半"), "天"),
]

_CHINESE_TIME_PATTERN = re.compile(
    r"(?P<num>半个?|[零〇一二三四五六七八九十百千万两兩点\.\d]+)(?P<unit>天|日|小时|个小时|时|分钟|分|秒钟?|秒)"
)


def _normalize_time_phrases(text: str) -> str:
    normalized = text
    for original, replacement in _TIME_REPLACEMENTS:
        normalized = normalized.replace(original, replacement)
    for original, replacement in _TIME_SUFFIX_MAP.items():
        normalized = normalized.replace(original, replacement)
    normalized = _replace_half_patterns(normalized)
    normalized = _replace_chinese_numerals(normalized)
    return normalized


def _replace_half_patterns(text: str) -> str:
    def _convert(match: re.Match[str], unit: str) -> str:
        raw = match.group(1)
        value = _parse_chinese_number(raw)
        if value is None:
            return match.group(0)
        value += 0.5
        return _format_unit(value, unit)

    result = text
    for pattern, unit in _HALF_PATTERNS:
        result = pattern.sub(lambda m, u=unit: _convert(m, u), result)

    # 单独处理“半小时”“半天”“半分钟”“半秒”
    result = re.sub(r"半个?小时", lambda _: _format_unit(0.5, "小时"), result)
    result = re.sub(r"半个?天", lambda _: _format_unit(0.5, "天"), result)
    result = re.sub(r"半个?分钟", lambda _: _format_unit(0.5, "分钟"), result)
    result = re.sub(r"半个?秒", lambda _: _format_unit(0.5, "秒"), result)
    return result


def _replace_chinese_numerals(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        num_str = match.group("num")
        unit = match.group("unit")
        value = _parse_chinese_number(num_str)
        if value is None:
            return match.group(0)

        if unit in {"刻钟"}:
            minutes = value * 15
            return _format_unit(minutes, "分钟")
        if unit in {"分钟", "分"}:
            return _format_unit(value, "分钟")
        if unit in {"秒", "秒钟"}:
            return _format_unit(value, "秒")
        if unit in {"小时", "个小时", "时"}:
            if float(value).is_integer():
                return _format_unit(value, "小时")
            minutes = value * 60
            return _format_unit(minutes, "分钟")
        if unit in {"天", "日"}:
            return _format_unit(value, "天")
        return match.group(0)

    return _CHINESE_TIME_PATTERN.sub(repl, text)


def _parse_chinese_number(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw:
        return None
    if raw in {"半", "半个"}:
        return 0.5
    if cn2an is not None:
        try:
            return float(cn2an.cn2an(raw, "smart"))
        except (ValueError, TypeError):
            pass

    fallback_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "兩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if raw in fallback_map:
        return float(fallback_map[raw])

    try:
        return float(raw)
    except ValueError:
        return None


def _format_unit(value: float, unit: str) -> str:
    if unit in {"分钟", "秒"}:
        total = value
        if abs(total - round(total)) < 1e-6:
            total = int(round(total))
        return f"{total}{unit}"
    if unit in {"小时", "天"}:
        if abs(value - round(value)) < 1e-6:
            value = int(round(value))
        return f"{value}{unit}"
    return f"{value}{unit}"


def extract_time_expression(text: str, base_time: Optional[datetime] = None) -> Optional[TimeExpression]:
    """抽取文本中的时间表达（绝对时间 / 相对时间 / 周期描述）。"""
    base_time = base_time or now_e8()
    original = text.strip()
    cleaned_no_date = re.sub(_date_pattern, "", original)
    cleaned_no_date = re.sub(r"\d{1,2}月\d{1,2}(?:日|号)?", "", cleaned_no_date)
    cleaned = _normalize_time_phrases(cleaned_no_date)
    expr = TimeExpression(raw_text=None)

    date_match = _date_pattern.search(original)
    if date_match:
        year_str, month_str, day_str = date_match.groups()
        try:
            year = int(year_str) if year_str else base_time.year
            month = int(month_str)
            day = int(day_str)
            candidate_date = datetime(year, month, day, tzinfo=EAST_EIGHT)
            if not year_str and candidate_date <= base_time:
                candidate_date = datetime(year + 1, month, day, tzinfo=EAST_EIGHT)
            expr.date_value = candidate_date
            expr.raw_text = date_match.group(0)
        except (TypeError, ValueError):
            expr.date_value = None

    for rel_match in _relative_pattern.finditer(cleaned):
        if not rel_match.group(0):
            continue
        days = float(rel_match.group("days") or 0)
        hours = float(rel_match.group("hours") or 0)
        minutes = float(rel_match.group("minutes") or 0)
        seconds = float(rel_match.group("seconds") or 0)
        if any([days, hours, minutes, seconds]):
            expr.relative_delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            expr.raw_text = rel_match.group(0)
            break

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
        if expr.date_value:
            candidate = expr.date_value.replace(hour=resolved_hour, minute=minute, second=0, microsecond=0)
        else:
            candidate = base_time.replace(hour=resolved_hour, minute=minute, second=0, microsecond=0)
            if candidate <= base_time:
                candidate += timedelta(days=1)
        expr.datetime_value = candidate
        expr.raw_text = expr.raw_text or time_match.group(0)
        expr.is_date_only = False

    if expr.date_value and expr.datetime_value is None:
        candidate = expr.date_value.replace(hour=9, minute=0, second=0, microsecond=0)
        expr.datetime_value = candidate
        expr.is_date_only = True

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
            expr.is_date_only = False

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
    """格式化闹钟落地时间：返回 ISO 8601 目标时间、事件与频次。"""
    if not time_expr:
        return "", extract_event(query), None

    target_iso = ""
    alarm_dt: Optional[datetime] = None

    if time_expr.is_date_only and time_expr.datetime_value:
        alarm_dt = time_expr.datetime_value
        if not alarm_dt.tzinfo:
            alarm_dt = alarm_dt.replace(tzinfo=EAST_EIGHT)
        alarm_dt = alarm_dt.astimezone(EAST_EIGHT)
        target_iso = alarm_dt.strftime("%Y-%m-%d %H:%M:%S")
        status = time_expr.periodic_status
        event = extract_event(query)
        return target_iso, event, status

    if time_expr.relative_delta:
        alarm_dt = base_time + time_expr.relative_delta
    elif time_expr.datetime_value:
        alarm_dt = time_expr.datetime_value
        if not time_expr.is_date_only and alarm_dt <= base_time:
            alarm_dt += timedelta(days=1)

    if alarm_dt:
        if not alarm_dt.tzinfo:
            alarm_dt = alarm_dt.replace(tzinfo=EAST_EIGHT)
        alarm_dt = alarm_dt.astimezone(EAST_EIGHT)
        target_iso = alarm_dt.strftime("%Y-%m-%d %H:%M:%S")

    status = time_expr.periodic_status
    event = extract_event(query)
    return target_iso, event, status


def extract_event(text: str) -> Optional[str]:
    """从提醒语句中抽取事件关键词。"""
    original = text.strip()
    cleaned = re.sub(_date_pattern, "", original)
    cleaned = re.sub(r"\d{1,2}月\d{1,2}(?:日|号)?", "", cleaned)
    cleaned = _normalize_time_phrases(cleaned)
    cleaned = re.sub(r"提醒(我)?", "", cleaned)
    cleaned = re.sub(r"(闹钟|设定|设置|帮我|一下|一个|请|安排|订个?|定个?)", "", cleaned)
    cleaned = re.sub(_relative_pattern, "", cleaned)
    cleaned = re.sub(_time_pattern, "", cleaned)
    cleaned = re.sub(_date_pattern, "", cleaned)
    cleaned = re.sub(r"\d{1,2}月\d{1,2}(?:日|号)?", "", cleaned)
    cleaned = cleaned.replace("每周", "").replace("每天", "")
    cleaned = cleaned.replace("今天", "").replace("明天", "").replace("明早", "")
    cleaned = cleaned.replace("后天", "")
    while cleaned and cleaned[0] in {"天", "日"}:
        cleaned = cleaned[1:]
    cleaned = re.sub(r"的$", "", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def extract_person_name(text: str) -> Optional[str]:
    """通过常见句式提取人名，用于通话/健康等功能。"""
    patterns = [
        re.compile(r"(?:帮我|请帮|麻烦|我想|我想要|我需要|想要|想)?给(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(?=(?:测|量|监测|检测|检查|检|测量|量血|测血|测体温|量体温))"),
        re.compile(r"(?:帮我|请帮|麻烦|我想|我想要|我需要|想要|想)?给(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(?=(?:打|拨).{0,3}(?:电话|视频))"),
        re.compile(r"(?:帮我|请帮|麻烦|我想|我想要|我需要|想要|想)?联系(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(?=(?:医生|大夫|老师|师傅)?(?:打电话|电话|视频)?$)"),
        re.compile(r"找(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(?=(?:医生|大夫|老师|师傅)?$)"),
        re.compile(r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})(?:医生|大夫|老师|师傅)"),
        re.compile(r"(?:查看|看看|了解|想看|想了解)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})的?(?:健康画像|健康状况|健康情况|健康状态)"),
        re.compile(r"给(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})"),
        re.compile(r"联系(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})"),
        re.compile(r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})的"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
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
    """将闹钟 target（ISO 8601）转换为易读的中文描述。"""
    if not target:
        return "指定时间"

    base_time = base_time or now_e8()

    alarm_dt: Optional[datetime] = None
    try:
        alarm_dt = datetime.strptime(target, "%Y-%m-%d %H:%M:%S").replace(tzinfo=EAST_EIGHT)
    except ValueError:
        alarm_dt = None

    if alarm_dt is None:
        try:
            alarm_dt = datetime.strptime(target, "%Y-%m-%d %H-%M-%S").replace(tzinfo=EAST_EIGHT)
        except ValueError:
            alarm_dt = None

    if alarm_dt is None:
        try:
            alarm_dt = datetime.fromisoformat(target)
        except ValueError:
            alarm_dt = None

    if alarm_dt is None:
        # 兼容旧格式，避免历史数据导致异常
        absolute_pattern = re.compile(r"(?P<days>\d+)d(?P<hours>\d+)h(?P<minutes>\d+)m")
        relative_pattern = re.compile(r"\+(?P<days>\d+)d(?P<hours>\d+)h(?P<minutes>\d+)m")

        if relative_match := relative_pattern.fullmatch(target):
            days = int(relative_match.group("days"))
            hours = int(relative_match.group("hours"))
            minutes = int(relative_match.group("minutes"))
            alarm_dt = base_time + timedelta(days=days, hours=hours, minutes=minutes)
        elif absolute_match := absolute_pattern.fullmatch(target):
            day_offset = int(absolute_match.group("days"))
            hour = int(absolute_match.group("hours"))
            minute = int(absolute_match.group("minutes"))
            alarm_dt = base_time + timedelta(days=day_offset)
            alarm_dt = alarm_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if alarm_dt is None:
        return target

    if not alarm_dt.tzinfo:
        alarm_dt = alarm_dt.replace(tzinfo=EAST_EIGHT)

    delta = alarm_dt - base_time
    if delta < timedelta():
        delta = timedelta()

    if delta <= timedelta(minutes=1):
        return "立即"

    if delta <= timedelta(hours=2):
        total_minutes = math.ceil(delta.total_seconds() / 60)
        days = total_minutes // (24 * 60)
        remaining_minutes = total_minutes % (24 * 60)
        hours = remaining_minutes // 60
        minutes = remaining_minutes % 60
        parts: list[str] = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        return "".join(parts) + "后"

    if alarm_dt.date() == base_time.date():
        day_text = "今天"
    elif alarm_dt.date() == (base_time.date() + timedelta(days=1)):
        day_text = "明天"
    elif alarm_dt.date() == (base_time.date() + timedelta(days=2)):
        day_text = "后天"
    else:
        day_text = alarm_dt.strftime("%m月%d日")

    time_text = alarm_dt.strftime("%H:%M")
    return f"{day_text}{time_text}"
