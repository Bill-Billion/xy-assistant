from __future__ import annotations

import pytest

from app.services.high_confidence_rules import HighConfidenceRuleEngine
from app.services.intent_definitions import IntentCode


@pytest.fixture(scope="module")
def engine() -> HighConfidenceRuleEngine:
    return HighConfidenceRuleEngine(default_city="长沙市")


def test_alarm_high_confidence(engine: HighConfidenceRuleEngine) -> None:
    match = engine.evaluate("帮我订个明早六点的闹钟提醒我晨跑")
    assert match is not None
    assert match.rule_result.intent_code == IntentCode.ALARM_CREATE
    assert match.analysis.result == "新增闹钟"
    assert match.analysis.confidence >= 0.96


def test_negative_sentence_skips(engine: HighConfidenceRuleEngine) -> None:
    match = engine.evaluate("不要给我设闹钟")
    assert match is None


def test_weather_detail(engine: HighConfidenceRuleEngine) -> None:
    match = engine.evaluate("明天北京会下雨吗？")
    assert match is not None
    assert match.rule_result.intent_code == IntentCode.WEATHER_TOMORROW
    assert match.weather_detail is not None
    assert match.weather_detail["location"] == "北京市"
    assert match.analysis.weather_condition in {None, "rain"}


def test_weather_default_city(engine: HighConfidenceRuleEngine) -> None:
    match = engine.evaluate("明天天气怎么样？")
    assert match is not None
    assert match.weather_detail["location"] == "长沙市"


def test_time_broadcast(engine: HighConfidenceRuleEngine) -> None:
    match = engine.evaluate("现在几点了？")
    assert match is not None
    assert match.rule_result.intent_code == IntentCode.TIME_BROADCAST
    assert match.analysis.result == "播报时间"
    assert match.analysis.target
    assert match.analysis.parsed_time == match.analysis.target
    assert match.analysis.time_source == "rule"
