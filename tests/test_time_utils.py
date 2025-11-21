from datetime import datetime, timedelta

from app.utils.time_utils import (
    EAST_EIGHT,
    derive_alarm_target,
    extract_time_expression,
    extract_person_name,
    sanitize_person_name,
    now_e8,
    parse_weather_date,
    resolve_calendar_target,
)


def test_parse_weather_date_today():
    base = datetime(2024, 9, 20, 10, 0, tzinfo=EAST_EIGHT)
    parsed = parse_weather_date("今天天气怎么样", base)
    assert parsed
    assert parsed.kind == "today"


def test_parse_weather_date_specific():
    base = datetime(2024, 9, 20, 10, 0, tzinfo=EAST_EIGHT)
    parsed = parse_weather_date("10月2日天气如何", base)
    assert parsed
    assert parsed.kind == "specific"
    assert parsed.value.month == 10
    assert parsed.value.day == 2


def test_derive_alarm_target_for_ambiguous_six():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    expr = extract_time_expression("帮我订个6点的闹钟", base)
    target, event, status = derive_alarm_target("帮我订个6点的闹钟", base, expr)
    assert target == "2024-09-20 18:00:00"
    assert event is None
    assert status is None


def test_relative_reminder():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "提醒我10分钟后煮饭"
    expr = extract_time_expression(query, base)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2024-09-20 14:10:00"
    assert event == "煮饭"
    assert status is None


def test_tomorrow_morning_alarm():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "明早9点提醒我吃药"
    expr = extract_time_expression(query, base)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2024-09-21 09:00:00"
    assert event == "吃药"
    assert status is None


def test_relative_chinese_numeral():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "十分钟之后提醒我喝水"
    expr = extract_time_expression(query, base)
    assert expr and expr.relative_delta == timedelta(minutes=10)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2024-09-20 14:10:00"
    assert event == "喝水"
    assert status is None


def test_relative_half_hour():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "半小时后提醒我拉伸"
    expr = extract_time_expression(query, base)
    assert expr and expr.relative_delta == timedelta(minutes=30)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2024-09-20 14:30:00"
    assert event == "拉伸"
    assert status is None


def test_derive_alarm_target_cleans_ding_ge():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "定个明早9点的闹钟"
    expr = extract_time_expression(query, base)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2024-09-21 09:00:00"
    assert event is None
    assert status is None


def test_extract_event_removes_relative_prefix():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "后天早上9点提醒我买火车票"
    expr = extract_time_expression(query, base)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target  # 解析出某个时间即可，由上层再结合 LLM 校正
    assert event == "买火车票"
    assert status is None


def test_resolve_calendar_target_tomorrow():
    base = datetime(2025, 10, 30, 10, 0, tzinfo=EAST_EIGHT)
    target, label = resolve_calendar_target("明天农历几号", base)
    assert target.date() == (base + timedelta(days=1)).date()
    assert label == "明天"


def test_resolve_calendar_target_specific_date():
    base = datetime(2025, 9, 20, 10, 0, tzinfo=EAST_EIGHT)
    target, label = resolve_calendar_target("10月2日黄历怎么样", base)
    assert target.month == 10
    assert target.day == 2
    assert label in {"10月2日", "10月02日"}


def test_sanitize_person_name_trims_measure_suffix():
    assert sanitize_person_name("小唐测") == "小唐"


def test_extract_person_name_for_measurement():
    assert extract_person_name("我想给小唐测血压") == "小唐"


def test_extract_person_name_for_relative():
    assert extract_person_name("帮我给爷爷量血压") == "爷爷"


def test_extract_person_name_for_doctor():
    assert extract_person_name("我要联系张三医生") == "张三"
