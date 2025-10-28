from datetime import datetime

import pytest

from app.services.intent_definitions import IntentCode
from app.services import intent_rules
from app.services.intent_rules import run_rules
from app.utils.time_utils import EAST_EIGHT


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    base = datetime(2024, 9, 20, 10, 0, tzinfo=EAST_EIGHT)

    def _fixed_now():
        return base

    monkeypatch.setattr(intent_rules, "now_e8", _fixed_now)
    yield


def test_weather_out_of_range():
    query = "2024年10月20日天气怎么样"
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.WEATHER_OUT_OF_RANGE
    assert result.result == "我还只能查到15天内的天气哦"


def test_health_monitor_person():
    result = run_rules("我要给爸爸血压监测")
    assert result
    assert result.intent_code == IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE
    assert result.result == "血压监测"
    assert result.target == "爸爸"


def test_mall_robot():
    result = run_rules("我要购买数字健康机器人")
    assert result
    assert result.intent_code == IntentCode.MALL_DIGITAL_HEALTH_ROBOT
    assert result.result == "数字健康机器人"


def test_chat_rule():
    result = run_rules("小雅陪我聊聊")
    assert result
    assert result.intent_code == IntentCode.CHAT


def test_alarm_relative_time():
    result = run_rules("提醒我10分钟后煮饭")
    assert result
    assert result.intent_code == IntentCode.ALARM_REMINDER
    assert result.target == "2024-09-20 10:10:00"
    assert result.event == "煮饭"


def test_alarm_periodic_time():
    result = run_rules("帮我每周三上午10点提醒我打电话")
    assert result
    assert result.intent_code == IntentCode.ALARM_REMINDER
    assert "每周三" in (result.status or "")


def test_alarm_week_token_no_precise_target():
    result = run_rules("帮我订个下周一早上9点的闹钟提醒我开组会")
    assert result
    assert result.intent_code == IntentCode.ALARM_CREATE
    assert result.target == ""


def test_calendar_rule_from_prompt():
    result = run_rules("明天适合搬家吗")
    assert result
    assert result.intent_code == IntentCode.CALENDAR_GENERAL


def test_home_service_recognition():
    result = run_rules("我家电视坏了，请帮我联系师傅维修")
    assert result
    assert result.intent_code == IntentCode.HOME_SERVICE_APPLIANCE



def test_health_monitor_general():
    result = run_rules("我要做健康检测")
    assert result
    assert result.intent_code == IntentCode.HEALTH_MONITOR_GENERAL
    assert result.result == "健康监测"


def test_health_monitor_sleep():
    result = run_rules("帮我看看睡眠情况")
    assert result
    assert result.intent_code == IntentCode.HEALTH_MONITOR_SLEEP
    assert result.result == "睡眠监测"


def test_health_knowledge_prefix_question():
    result = run_rules("怎么判断有没有高血压")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == "判断高血压"


def test_health_knowledge_suffix_question():
    result = run_rules("鼻炎老是犯怎么办")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == "处理鼻炎老是犯"


def test_health_knowledge_tell_me():
    result = run_rules("给我讲讲高血压相关知识")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == "高血压相关知识"


def test_health_knowledge_want_to_learn():
    result = run_rules("我想了解下高血压日常吃什么")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == "高血压日常吃什么"


def test_health_evaluation_keyword():
    result = run_rules("帮我做健康评估")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EVALUATION
    assert result.result == "健康评估"


def test_health_evaluation_variation():
    result = run_rules("请帮我评估一下健康状况")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EVALUATION
    assert result.result == "健康评估"


def test_cognitive_evaluation():
    result = run_rules("我要做认知评估")
    assert result
    assert result.intent_code == IntentCode.HEALTH_EVALUATION
    assert result.result == "健康评估"


def test_metric_keyword_takes_precedence_over_evaluation():
    result = run_rules("我要做血压监测评估")
    assert result
    assert result.intent_code == IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE
    assert result.result == "血压监测"


def test_close_music_command():
    result = run_rules("请帮我关闭音乐")
    assert result
    assert result.intent_code == IntentCode.ENTERTAINMENT_MUSIC_OFF
    assert result.result == "关闭音乐"


def test_close_audiobook_command():
    result = run_rules("把听书关闭")
    assert result
    assert result.intent_code == IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF
    assert result.result == "关闭听书"


def test_close_opera_command():
    result = run_rules("关闭戏曲")
    assert result
    assert result.intent_code == IntentCode.ENTERTAINMENT_OPERA_OFF
    assert result.result == "关闭戏曲"


def test_screen_off_command():
    result = run_rules("帮我息屏")
    assert result
    assert result.intent_code == IntentCode.DEVICE_SCREEN_OFF
    assert result.result == "息屏"
