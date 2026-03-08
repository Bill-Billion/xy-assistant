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


def test_weather_now_temperature_query():
    result = run_rules("现在多少度")
    assert result
    assert result.intent_code == IntentCode.WEATHER_TODAY
    assert result.weather_condition == "temperature"
    assert result.time_text == "现在"


def test_weather_outdoor_temperature_query_defaults_to_today():
    result = run_rules("室外多少度")
    assert result
    assert result.intent_code == IntentCode.WEATHER_TODAY
    assert result.weather_condition == "temperature"
    assert result.time_text == "现在"


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
    assert result.parsed_time
    assert result.time_text == "明天"


def test_home_service_recognition():
    result = run_rules("我家电视坏了，请帮我联系师傅维修")
    assert result
    assert result.intent_code == IntentCode.HOME_SERVICE_APPLIANCE


@pytest.mark.parametrize(
    ("query", "expected_result"),
    [
        ("我想看电视", "小雅电影"),
        ("我想看电影", "小雅电影"),
        ("打开小雅电影", "小雅电影"),
    ],
)
def test_movie_queries_do_not_fall_into_home_service(query, expected_result):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.ENTERTAINMENT_MOVIE
    assert result.result == expected_result



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


def test_brightness_up_returns_plus_10():
    result = run_rules("把屏幕亮度调高10%")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_BRIGHTNESS_UP
    assert result.result == "亮度调高"
    assert result.target == "+10"


def test_brightness_down_returns_minus_10():
    result = run_rules("亮度调低一点")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_BRIGHTNESS_DOWN
    assert result.result == "亮度调低"
    assert result.target == "-10"


def test_brightness_set_absolute_value():
    result = run_rules("亮度调到30")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_BRIGHTNESS_UP
    assert result.result == "亮度调高"
    assert result.target == "30"


def test_sound_up_returns_plus_10():
    result = run_rules("音量高1档")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_UP
    assert result.result == "声音调高"
    assert result.target == "+10"


def test_sound_down_returns_minus_10():
    result = run_rules("把声音调小点")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_DOWN
    assert result.result == "声音调低"
    assert result.target == "-10"


def test_sound_set_absolute_value():
    result = run_rules("音量调到40")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_UP
    assert result.result == "声音调高"
    assert result.target == "40"


def test_sound_mute_delegates_to_llm():
    assert run_rules("把音量静音") is None


def test_sound_max_volume_delegates_to_llm():
    assert run_rules("把音量调到最大") is None


@pytest.mark.parametrize(
    ("query", "expected_target", "expected_clarify"),
    [
        ("取消明天早上8点的闹钟", "2024-09-21 08:00:00", False),
        ("删除明天早上8点的提醒", "2024-09-21 08:00:00", False),
        ("取消闹钟", "", True),
    ],
)
def test_alarm_cancel_toc_variants(query, expected_target, expected_clarify):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.ALARM_CANCEL
    assert result.result == "取消闹钟"
    assert (result.target or "") == expected_target
    assert result.need_clarify is expected_clarify


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("给我讲讲高血压相关知识", "高血压相关知识"),
        ("怎么判断有没有高血压", "判断高血压"),
        ("被蜜蜂蛰了怎么办", "处理被蜜蜂蛰了"),
    ],
)
def test_health_education_toc_variants(query, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == expected_target


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("帮我找王医生看病", "王医生"),
        ("帮我找李医生看诊", "李医生"),
        ("能不能安排张医生问诊", "张医生"),
        ("能不能安排个远程问诊，我想让专家听听。", ""),
    ],
)
def test_health_specialist_toc_variants(query, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.HEALTH_SPECIALIST
    assert result.result == "名医问诊"
    assert result.target == expected_target


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("新增一个用药计划", ""),
        ("添加一个服药计划", ""),
        ("新建一个每天吃维生素d的计划", "维生素D"),
    ],
)
def test_medication_plan_toc_variants(query, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.MEDICATION_REMINDER_CREATE
    assert result.result == "用药计划"
    assert (result.target or "") == expected_target


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_result", "expected_target"),
    [
        ("我想联系家人", IntentCode.COMMUNICATION_GENERAL, "小雅通话", ""),
        ("我要做服务预约", IntentCode.HOME_SERVICE_GENERAL, "小雅预约", ""),
        ("给我预约做饭服务", IntentCode.HOME_SERVICE_GENERAL, "小雅预约", ""),
        ("打开二胡学习视频", IntentCode.EDUCATION_GENERAL, "小雅教育", "二胡"),
        ("我想学广场舞", IntentCode.EDUCATION_GENERAL, "小雅教育", "广场舞"),
        ("教我跳跳新的广场舞。", IntentCode.EDUCATION_GENERAL, "小雅教育", "广场舞"),
        ("想跟着学写楷书，有视频课吗？", IntentCode.EDUCATION_GENERAL, "小雅教育", "写楷书"),
        ("我想看八段锦", IntentCode.HEALTH_EDUCATION, "健康科普", "八段锦"),
        ("我想看电视", IntentCode.ENTERTAINMENT_MOVIE, "小雅电影", ""),
        ("我想看电影", IntentCode.ENTERTAINMENT_MOVIE, "小雅电影", ""),
        ("打开小雅娱乐", IntentCode.ENTERTAINMENT_GENERAL, "娱乐管家", ""),
        ("我想娱乐一下", IntentCode.ENTERTAINMENT_GENERAL, "娱乐管家", ""),
    ],
)
def test_general_toc_entry_variants(query, expected_intent, expected_result, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == expected_intent
    assert result.result == expected_result
    assert (result.target or "") == expected_target


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_target"),
    [
        ("帮我联系张三的家庭医生", IntentCode.FAMILY_DOCTOR_CONTACT, "张三"),
        ("帮我联系我爸的家庭医生", IntentCode.FAMILY_DOCTOR_CONTACT, "我爸"),
        ("帮我给王医生打个电话", IntentCode.FAMILY_DOCTOR_CALL_AUDIO, "王医生"),
    ],
)
def test_family_doctor_toc_variants(query, expected_intent, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == expected_intent
    assert result.result == "家庭医生"
    assert result.target == expected_target


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("帮我瞧瞧老伴最近身体数据怎么样。", "老伴"),
        ("XX的健康状况是怎样的", "XX"),
    ],
)
def test_health_profile_colloquial_variants(query, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.HEALTH_PROFILE
    assert result.result == "健康画像"
    assert result.target == expected_target


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("帮我给小唐量下血压，他晚上老眩晕。", IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE),
        ("爸今晚要吃药，顺便帮他查查血糖数据。", IntentCode.HEALTH_MONITOR_BLOOD_SUGAR),
    ],
)
def test_health_monitor_colloquial_measurement_variants(query, expected_intent):
    result = run_rules(query)
    assert result
    assert result.intent_code == expected_intent


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("菜单里是不是有更新选项？帮我找找。", IntentCode.SETTINGS_GENERAL),
        ("身体不太舒服，打开健康咨询给我指点指点。", IntentCode.HEALTH_DOCTOR_GENERAL),
    ],
)
def test_settings_and_health_doctor_colloquial_variants(query, expected_intent):
    result = run_rules(query)
    assert result
    assert result.intent_code == expected_intent


def test_sound_relative_percentage_delegates_to_llm():
    assert run_rules("音量调大百分之三十") is None
    assert run_rules("音量调大30%") is None


def test_sound_absolute_percentage_value_is_local():
    result = run_rules("音量调到30%")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_UP
    assert result.result == "声音调高"
    assert result.target == "30"


def test_sound_absolute_chinese_percentage_value_is_local():
    result = run_rules("音量调到百分之三十")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_UP
    assert result.result == "声音调高"
    assert result.target == "30"


def test_sound_absolute_set_cheng_local():
    result = run_rules("把音量设成30%")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_SOUND_UP
    assert result.result == "声音调高"
    assert result.target == "30"


def test_brightness_relative_percentage_delegates_to_llm():
    assert run_rules("屏幕亮度调高百分之三十") is None


def test_brightness_up_when_state_is_dark():
    result = run_rules("屏幕有点暗，亮一点")
    assert result
    assert result.intent_code == IntentCode.SETTINGS_BRIGHTNESS_UP
    assert result.result == "亮度调高"
    assert result.target == "+10"


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_result"),
    [
        ("我想眯一会儿，不想它一直亮着。", IntentCode.DEVICE_SCREEN_OFF, "息屏"),
        ("小睡醒了搞不清现在是啥时辰，你报一下。", IntentCode.TIME_BROADCAST, "播报时间"),
        ("下周二是不是腊八节啊？", IntentCode.CALENDAR_GENERAL, "日期时间和万年历"),
        ("这阵子浑身乏力，帮我做个整体评估看看。", IntentCode.HEALTH_EVALUATION, "健康评估"),
        ("最近膝盖疼，想预约个专家远程问问。", IntentCode.HEALTH_SPECIALIST, "名医问诊"),
        ("看看最近拍的小孙女。", IntentCode.ALBUM, "小雅相册"),
        ("想听会儿评书，有啥推荐。", IntentCode.ENTERTAINMENT_OPERA, "小雅曲艺"),
        ("最近想买点健康零食，帮我看看。", IntentCode.MALL_HEALTH_FOOD, "健康食疗产品"),
    ],
)
def test_rule_direct_match_for_colloquial_fuzzy_queries(query, expected_intent, expected_result):
    result = run_rules(query)
    assert result
    assert result.intent_code == expected_intent
    assert result.result == expected_result


def test_audio_call_colloquial_variant_matches_family_member_target():
    result = run_rules("帮我打给闺女，语音就行。")
    assert result
    assert result.intent_code == IntentCode.COMMUNICATION_CALL_AUDIO
    assert result.result == "小雅音频通话"
    assert result.target == "闺女"


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("熬夜后总心慌，有啥缓解的小贴士吗？", "缓解熬夜后总心慌"),
        ("血脂高的老人吃饭应该注意点啥？", "血脂高的老人吃饭"),
    ],
)
def test_health_education_colloquial_advice_queries(query, expected_target):
    result = run_rules(query)
    assert result
    assert result.intent_code == IntentCode.HEALTH_EDUCATION
    assert result.result == "健康科普"
    assert result.target == expected_target
