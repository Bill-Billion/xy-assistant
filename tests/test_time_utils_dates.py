from __future__ import annotations

from datetime import datetime

import pytest

from app.utils.time_utils import (
    EAST_EIGHT,
    derive_alarm_target,
    extract_time_expression,
)


def _base_time() -> datetime:
    return datetime(2025, 10, 30, 10, 30, tzinfo=EAST_EIGHT)


@pytest.mark.parametrize(
    "query",
    [
        "11月25提醒我过生日",
        "11月25号提醒我过生日",
        "11月25日提醒我过生日",
    ],
)
def test_date_only_alarm(query: str) -> None:
    base = _base_time()
    expr = extract_time_expression(query, base)
    assert expr is not None
    assert expr.date_value is not None
    assert expr.datetime_value is not None
    assert expr.datetime_value.strftime("%Y-%m-%d %H:%M:%S") == "2025-11-25 09:00:00"
    assert expr.is_date_only is True
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2025-11-25 09:00:00", f"target={target}, expr={expr.datetime_value}"
    assert event == "过生日"
    assert status is None


def test_date_with_time_alarm() -> None:
    base = _base_time()
    query = "11月25日晚上7点提醒我过生日"
    expr = extract_time_expression(query, base)
    assert expr is not None
    assert expr.datetime_value is not None
    assert expr.is_date_only is False
    target, event, status = derive_alarm_target(query, base, expr)
    assert target == "2025-11-25 19:00:00"
    assert event == "过生日"
    assert status is None
