from datetime import datetime

from app.utils.time_utils import (
    EAST_EIGHT,
    derive_alarm_target,
    extract_time_expression,
    now_e8,
    parse_weather_date,
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
    assert target == "0d18h0m"
    assert event is None
    assert status is None


def test_relative_reminder():
    base = datetime(2024, 9, 20, 14, 0, tzinfo=EAST_EIGHT)
    query = "提醒我10分钟后煮饭"
    expr = extract_time_expression(query, base)
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "+0d0h10m"
    assert event == "煮饭"
    assert status is None
