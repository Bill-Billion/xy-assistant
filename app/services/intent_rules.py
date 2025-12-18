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
    resolve_calendar_target,
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
    weather_condition: Optional[str] = None
    parsed_time: Optional[str] = None
    time_text: Optional[str] = None
    time_confidence: Optional[float] = None
    time_source: Optional[str] = None


# 健康监测关键词映射：不同检测需求需返回对应细分意图与固定 result。
_health_metric_map = {
    "测血压": (IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE, "血压监测"),
    "血压监测": (IntentCode.HEALTH_MONITOR_BLOOD_PRESSURE, "血压监测"),
    "血氧监测": (IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN, "血氧监测"),
    "测血氧": (IntentCode.HEALTH_MONITOR_BLOOD_OXYGEN, "血氧监测"),
    "心率监测": (IntentCode.HEALTH_MONITOR_HEART_RATE, "心率监测"),
    "测心率": (IntentCode.HEALTH_MONITOR_HEART_RATE, "心率监测"),
    "血糖监测": (IntentCode.HEALTH_MONITOR_BLOOD_SUGAR, "血糖监测"),
    "测血糖": (IntentCode.HEALTH_MONITOR_BLOOD_SUGAR, "血糖监测"),
    "血脂监测": (IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS, "血脂监测"),
    "测血脂": (IntentCode.HEALTH_MONITOR_BLOOD_LIPIDS, "血脂监测"),
    "称体重": (IntentCode.HEALTH_MONITOR_WEIGHT, "体重监测"),
    "体重监测": (IntentCode.HEALTH_MONITOR_WEIGHT, "体重监测"),
    "测体温": (IntentCode.HEALTH_MONITOR_BODY_TEMPERATURE, "体温监测"),
    "体温监测": (IntentCode.HEALTH_MONITOR_BODY_TEMPERATURE, "体温监测"),
    "血红蛋白监测": (IntentCode.HEALTH_MONITOR_HEMOGLOBIN, "血红蛋白监测"),
    "测血红蛋白": (IntentCode.HEALTH_MONITOR_HEMOGLOBIN, "血红蛋白监测"),
    "尿酸监测": (IntentCode.HEALTH_MONITOR_URIC_ACID, "尿酸监测"),
    "测尿酸": (IntentCode.HEALTH_MONITOR_URIC_ACID, "尿酸监测"),
    "睡眠监测": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
    "睡眠情况": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
    "睡眠质量": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
    "睡眠状态": (IntentCode.HEALTH_MONITOR_SLEEP, "睡眠监测"),
}

_health_evaluation_keywords = [
    "健康评估",
    "健康评价",
    "健康状况评估",
    "健康情况评估",
    "健康状态评估",
    "认知评估",
    "认知测评",
    "记忆评估",
    "记忆测评",
    "评估健康",
    "功能评估",
]

_health_evaluation_support_terms = [
    "健康",
    "健康状况",
    "健康情况",
    "健康状态",
    "身体状况",
    "身体情况",
    "身体状态",
]

_health_context_terms = {
    "健康",
    "疾病",
    "病",
    "症状",
    "病情",
    "治疗",
    "诊断",
    "预防",
    "养生",
    "保健",
    "康复",
    "用药",
    "药物",
    "饮食",
    "作息",
    "养护",
    "护理",
    "调理",
    "康养",
    "运动",
    "锻炼",
    "疼痛",
    "头痛",
    "头疼",
    "头晕",
    "眩晕",
    "乏力",
    "疲劳",
    "发烧",
    "发热",
    "感冒",
    "咳嗽",
    "咳痰",
    "喉咙",
    "咽炎",
    "鼻炎",
    "胃",
    "肠",
    "肝",
    "肾",
    "胆",
    "肺",
    "眼睛",
    "视力",
    "血压",
    "高血压",
    "低血压",
    "血糖",
    "血脂",
    "血氧",
    "心脏",
    "心率",
    "心跳",
    "糖尿病",
    "骨质疏松",
    "关节",
    "睡眠",
    "失眠",
    "焦虑",
    "抑郁",
    "情绪",
    "心理",
    "康复训练",
}

_medication_keywords = [
    "用药",
    "服药",
    "吃药",
    "药物",
]

_medication_view_terms = [
    "用药提醒",
    "用药安排",
    "用药计划",
    "服药提醒",
    "服药计划",
    "吃药提醒",
    "吃药计划",
    "药物提醒",
]

_medication_view_verbs = [
    "打开",
    "查看",
    "看看",
    "看下",
    "看一下",
    "看一看",
    "有没有",
    "有吗",
    "查询",
    "了解",
    "在哪",
    "哪里",
    "怎么",
    "如何",
    "怎样",
    "哪些",
]

_medication_create_triggers = [
    "新增",
    "新建",
    "添加",
    "安排",
    "设定",
    "设个",
    "设一下",
    "设一个",
    "定个",
    "定一个",
    "订个",
    "订一个",
    "帮我定",
    "帮我设",
    "设置",
    "设",
]

# 聊天严格关键词，仅当出现这些词才允许直接触发聊天意图
_chat_strict_keywords = {
    "聊天",
    "聊聊",
    "聊会儿",
    "聊一会",
    "陪我聊",
    "陪我聊聊",
    "陪我说说话",
    "说说话",
    "唠嗑",
    "唠会儿",
}

_health_profile_keywords = [
    "健康状况",
    "健康情况",
    "健康状态",
    "身体状况",
    "身体情况",
    "身体状态",
    "健康档案",
    "健康信息",
]

# 健康操/养生操关键词，优先归入健康科普
_health_exercise_keywords = [
    "八段锦",
    "养生操",
    "健身操",
    "广播体操",
    "康复操",
    "气功",
    "舒缓操",
]

_topic_suffix_cleanup = [
    "判断方法",
    "判断",
    "方法",
    "怎么办",
    "怎么做",
    "怎么判断",
    "如何判断",
    "有哪些症状",
    "症状有哪些",
    "症状",
    "征兆",
    "表现",
    "要注意什么",
    "需要注意什么",
]

_entertainment_pause_map = {
    "音乐": IntentCode.ENTERTAINMENT_MUSIC_OFF,
    "歌": IntentCode.ENTERTAINMENT_MUSIC_OFF,
    "听书": IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF,
    "小说": IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF,
    "戏曲": IntentCode.ENTERTAINMENT_OPERA_OFF,
    "曲艺": IntentCode.ENTERTAINMENT_OPERA_OFF,
}

_entertainment_resume_keywords = [
    "继续播放",
    "继续听",
    "接着播",
    "恢复播放",
    "继续放",
]

_chat_strict_keywords = {
    "聊天",
    "聊聊",
    "聊会儿",
    "聊一会",
    "陪我聊",
    "陪我聊聊",
    "陪我说说话",
    "说说话",
    "唠嗑",
    "唠会儿",
}

_settings_general_keywords = {
    "小雅设置",
    "设置界面",
    "设置页面",
    "设置中心",
    "设置菜单",
    "设置功能",
    "设置选项",
    "系统设置",
    "设备设置",
    "打开设置",
    "进入设置",
    "去设置",
}

_settings_general_exact = {
    "设置",
    "设置一下",
    "设置下",
    "设置一下下",
}

_settings_exclusion_keywords = {
    "提醒",
    "闹钟",
    "天气",
    "气温",
    "农历",
    "黄历",
    "日期",
    "时间",
    "几点",
    "学习",
    "学",
    "课程",
    "家政",
    "维修",
    "服务",
    "预约",
    "师傅",
    "娱乐",
    "音乐",
    "听书",
    "戏曲",
    "曲艺",
    "游戏",
    "斗地主",
    "象棋",
    "笑话",
    "聊天",
    "通话",
    "打电话",
    "视频",
    "相册",
    "照片",
    "商城",
    "购买",
    "下单",
    "商品",
    "订单",
    "机器人",
    "终端",
    "用品",
    "医生",
    "问诊",
    "咨询",
    "家庭医生",
    "名医",
    "医生",
    "健康",
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
    "评估",
    "测量",
    "监测",
    "科普",
    "画像",
    "用药",
    "服药",
    "吃药",
    "药物",
}
_settings_exclusion_keywords.update(_medication_view_terms)
_settings_exclusion_keywords.update(_health_evaluation_keywords)
_settings_exclusion_keywords.update(_health_profile_keywords)
_settings_exclusion_keywords.update(_health_context_terms)
_settings_exclusion_keywords.update(_health_metric_map.keys())

_joke_keywords = [
    "讲个笑话",
    "讲笑话",
    "来个笑话",
    "讲段子",
    "逗我笑",
    "讲个搞笑的",
]

_profile_name_pattern = re.compile(
    r"(?:我想)?(?:了解|看看|查看|查询|知道|想看|想了解|想知道)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,8})的?(?:健康状况|健康情况|健康状态|身体状况|身体情况|身体状态|健康档案)"
)
_health_context_terms.update(_health_metric_map.keys())

_knowledge_action_map = {
    "判断": "判断",
    "识别": "识别",
    "区分": "区分",
    "处理": "处理",
    "解决": "处理",
    "应对": "应对",
    "缓解": "缓解",
    "预防": "预防",
    "怎么办": "处理",
    "该怎么办": "处理",
    "咋办": "处理",
    "如何办": "处理",
}

_knowledge_prefix_patterns: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r"^(?:我|我们|咱们)?(?:想|要)?(?:了解|知道|看看)(?:一下|下)?(?P<topic>.+)$"), None),
    (re.compile(r"^(?:请|能否|能不能|帮我|帮忙)?(?:给我|给咱|给家里人)?(?:简单|详细)?(?:讲讲|介绍|说说|科普|解释|说明)(?P<topic>.+)$"), None),
    (re.compile(r"^(?:请|能否|能不能|帮我|帮忙)?(?:告诉|告知|教)(?:我|一下)?(?P<topic>.+)$"), None),
    (re.compile(r"^(?:请|能否|能不能|帮忙)?(?:给我)?科普一下(?P<topic>.+)$"), None),
    (re.compile(r"^(?:怎么|如何|怎样)(判断|识别|区分)(?P<topic>.+)$"), "判断"),
    (re.compile(r"^(?:怎么|如何|怎样)(处理|解决|应对|缓解|预防)(?P<topic>.+)$"), "处理"),
    (re.compile(r"^(?:怎么|如何|怎样)预防(?P<topic>.+)$"), "预防"),
]

_knowledge_suffix_patterns: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r"(?P<topic>.+?)(?:怎么|如何|怎样)(处理|解决|应对|缓解|预防)(?:好)?$"), "处理"),
    (re.compile(r"(?P<topic>.+?)(?:该)?(怎么办|咋办|如何办)$"), "处理"),
    (re.compile(r"(?P<topic>.+?)的?(相关)?知识$"), None),
]

_weather_condition_patterns: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"晴|晴朗|阳光|太阳"), "sunny"),
    (re.compile(r"雪|下雪|有雪|降雪"), "snow"),
    (re.compile(r"雨|下雨|降雨|雨水"), "rain"),
    (re.compile(r"风|刮风|大风|风大"), "wind"),
    (re.compile(r"热|炎热|高温|很热"), "hot"),
    (re.compile(r"冷|寒冷|低温|很冷"), "cold"),
    (re.compile(r"雾霾|空气质量|污染"), "air_quality"),
    (re.compile(r"降雨概率|下不下雨|会不会下雨"), "rain_chance"),
    (re.compile(r"温度|气温|几度"), "temperature"),
]

_topic_leading_phrases = [
    "关于",
    "有关",
    "针对",
    "一些",
    "哪些",
    "哪种",
    "什么是",
    "什么叫",
    "什么叫做",
    "什么",
    "怎样才",
    "如何才",
    "怎么才",
    "怎么样",
    "如何能",
    "怎样能",
    "为什么",
    "为何",
    "有没有",
    "是否",
    "是不是",
    "会不会",
    "需不需要",
    "用不用",
]

_topic_pronoun_prefixes = [
    "我",
    "自己",
    "我们",
    "家人",
    "老人",
    "爸",
    "妈妈",
    "爸爸",
    "父亲",
    "母亲",
    "孩子",
    "他",
    "她",
    "他们",
    "她们",
    "他爸",
    "他妈",
    "她爸",
    "她妈",
]

_topic_trailing_phrases = [
    "一下",
    "一下下",
    "呗",
    "吧",
    "么",
    "吗",
    "啊",
    "呀",
    "呢",
    "嘛",
    "呀",
    "的",
    "情况",
    "方法",
]


def apply_weather_rule(context: RuleContext) -> Optional[RuleResult]:
    """天气相关意图匹配，识别日期与关注的具体天气要素。"""
    query = context.query
    if not any(keyword in query for keyword in ["天气", "气温", "温度", "晴", "雨", "雪", "风", "雾霾", "空气质量"]):
        return None

    weather_condition = None
    for pattern, condition in _weather_condition_patterns:
        if pattern.search(query):
            weather_condition = condition
            break

    parsed = parse_weather_date(query, context.base_time)
    if not parsed:
        return None

    date_kind, date_value = parsed.kind, parsed.value
    if date_kind == "today":
        today_iso = context.base_time.date().isoformat()
        return RuleResult(
            IntentCode.WEATHER_TODAY,
            "今天天气",
            target="今天",
            weather_condition=weather_condition,
            parsed_time=today_iso,
            time_text="今天",
            time_confidence=0.99,
            time_source="rule",
        )
    if date_kind == "tomorrow":
        target_time = context.base_time + timedelta(days=1)
        target_iso = target_time.date().isoformat()
        return RuleResult(
            IntentCode.WEATHER_TOMORROW,
            "明天天气",
            target="明天",
            weather_condition=weather_condition,
            parsed_time=target_iso,
            time_text="明天",
            time_confidence=0.99,
            time_source="rule",
        )
    if date_kind == "day_after":
        target_time = context.base_time + timedelta(days=2)
        target_iso = target_time.date().isoformat()
        return RuleResult(
            IntentCode.WEATHER_DAY_AFTER,
            "后天天气",
            target="后天",
            weather_condition=weather_condition,
            parsed_time=target_iso,
            time_text="后天",
            time_confidence=0.98,
            time_source="rule",
        )
    if date_kind == "specific":
        time_phrase = parsed.phrase or date_value.strftime("%Y-%m-%d")
        if not is_within_days(date_value, context.base_time, 15):
            return RuleResult(
                IntentCode.WEATHER_OUT_OF_RANGE,
                "我还只能查到15天内的天气哦",
                target="",
                weather_condition=weather_condition,
                parsed_time=date_value.isoformat(),
                time_text=time_phrase,
                time_confidence=0.9,
                time_source="rule",
            )
        return RuleResult(
            IntentCode.WEATHER_SPECIFIC,
            "特定日期天气",
            target=date_value.date().isoformat(),
            weather_condition=weather_condition,
            parsed_time=date_value.isoformat(),
            time_text=time_phrase,
            time_confidence=0.9,
            time_source="rule",
        )
    return None


def apply_calendar_rule(context: RuleContext) -> Optional[RuleResult]:
    """处理日历、黄历、吉日等需求。"""
    terms = ["几月几日", "农历", "黄历", "黄道吉日", "节气", "日期", "几号", "万年历", "适合搬家", "宜搬家", "搬家吉日"]
    if any(term in context.query for term in terms) or ("适合" in context.query and "搬家" in context.query):
        target_date, time_text = resolve_calendar_target(context.query, context.base_time)
        lunar = get_lunar_info(target_date)
        summary = format_lunar_summary(lunar) if lunar else None
        reasoning_detail = f"提供{time_text or '当日'}的日期及万年历信息"
        if summary:
            reasoning_detail += f"，包含：{summary}"
        parsed_time = target_date.isoformat()
        return RuleResult(
            IntentCode.CALENDAR_GENERAL,
            "日期时间和万年历",
            reasoning=reasoning_detail,
            parsed_time=parsed_time,
            time_text=time_text or "今天",
            time_confidence=0.98,
            time_source="rule",
        )
    return None


def apply_time_rule(context: RuleContext) -> Optional[RuleResult]:
    """时间播报与闹钟提醒解析。"""
    q = context.query
    if any(keyword in q for keyword in _medication_keywords) or "用药提醒" in q or "服药提醒" in q or "吃药提醒" in q:
        return None
    week_tokens = ["下周", "下星期", "下礼拜", "这周", "本周", "周一", "周二", "周三", "周四", "周五", "周六", "周日", "周天"]
    has_week_token = any(token in context.query for token in week_tokens)
    if "几点" in context.query or "现在时间" in context.query:
        return RuleResult(IntentCode.TIME_BROADCAST, "播报时间")
    if "闹钟" in context.query:
        if any(token in context.query for token in ["打开", "查看", "进入"]):
            return RuleResult(IntentCode.ALARM_VIEW, "闹钟界面", target="")
        time_expr = extract_time_expression(context.query, context.base_time)
        if not time_expr:
            return RuleResult(IntentCode.ALARM_CREATE, "新增闹钟", target="")
        target_str, event, status = derive_alarm_target(context.query, context.base_time, time_expr)
        if has_week_token:
            target_str = ""
        return RuleResult(IntentCode.ALARM_CREATE, "新增闹钟", target=target_str, event=event, status=status)
    if "提醒" in context.query:
        time_expr = extract_time_expression(context.query, context.base_time)
        target_str, event, status = derive_alarm_target(context.query, context.base_time, time_expr)
        if has_week_token:
            target_str = ""
        return RuleResult(IntentCode.ALARM_REMINDER, "新增闹钟", target=target_str, event=event, status=status)
    return None


def apply_settings_rule(context: RuleContext) -> Optional[RuleResult]:
    """系统设置相关指令（声音/亮度/息屏等）。"""
    q = context.query
    # 排除领域关键词，防止拦截其他功能
    exclusion_tokens = (
        set(_settings_exclusion_keywords)
        | set(_medication_keywords)
        | set(_medication_view_terms)
        | set(_medication_create_triggers)
    )
    if any(token in q for token in exclusion_tokens):
        return None
    if any(term in q for term in ["关机", "关闭屏幕", "息屏", "屏幕关闭", "关闭显示"]):
        return RuleResult(IntentCode.DEVICE_SCREEN_OFF, "息屏", confidence=0.95)
    if "声音" in q or "音量" in q:
        if any(token in q for token in ["低", "小", "减", "静音"]):
            return RuleResult(IntentCode.SETTINGS_SOUND_DOWN, "声音调低")
        if any(token in q for token in ["高", "大", "增", "加", "最大", "提高"]):
            return RuleResult(IntentCode.SETTINGS_SOUND_UP, "声音调高")
    if "亮度" in q:
        if any(token in q for token in ["低", "暗", "减"]):
            return RuleResult(IntentCode.SETTINGS_BRIGHTNESS_DOWN, "亮度调低")
        if any(token in q for token in ["高", "亮", "增"]):
            return RuleResult(IntentCode.SETTINGS_BRIGHTNESS_UP, "亮度调高")
    general_trigger = False
    stripped = q.strip()
    if any(keyword in q for keyword in _settings_general_keywords):
        general_trigger = True
    elif stripped in _settings_general_exact:
        general_trigger = True
    elif "设置" in q:
        if not any(exclusion in q for exclusion in _settings_exclusion_keywords):
            general_trigger = True
    if general_trigger:
        return RuleResult(IntentCode.SETTINGS_GENERAL, "小雅设置")
    return None


def _normalize_topic(raw_topic: str, action: str | None) -> str:
    """清洗主题文本，保留核心疾病/症状关键词。"""
    topic = (raw_topic or "").strip()
    topic = re.sub(r"[？?！!。．\.、,，]+$", "", topic)
    topic = topic.strip()
    for phrase in _topic_leading_phrases:
        if topic.startswith(phrase):
            topic = topic[len(phrase):].lstrip()
    for prefix in _topic_pronoun_prefixes:
        if topic.startswith(prefix):
            topic = topic[len(prefix):].lstrip("的 ")
    topic = topic.strip()
    for phrase in _topic_trailing_phrases:
        if topic.endswith(phrase):
            if phrase == "么" and topic.endswith("什么"):
                continue
            topic = topic[: -len(phrase)].rstrip()
    topic = topic.strip()
    for suffix in _topic_suffix_cleanup:
        if topic.endswith(suffix):
            topic = topic[: -len(suffix)].rstrip()
    topic = topic.strip()
    if action:
        action_clean = _knowledge_action_map.get(action, action)
        if topic:
            return f"{action_clean}{topic}"
        return action_clean
    return topic


def _extract_health_knowledge_topic(query: str) -> Optional[str]:
    """识别“讲讲/怎么判断/怎么办”等健康知识类问题，返回归一化主题。"""
    text = query.strip()
    if extract_person_name(text) and any(term in text for term in _health_profile_keywords):
        return None
    for pattern, action in _knowledge_prefix_patterns:
        match = pattern.match(text)
        if not match:
            continue
        topic = _normalize_topic(match.group("topic"), action)
        if topic and any(term in topic for term in _health_context_terms):
            return topic
    for pattern, action in _knowledge_suffix_patterns:
        match = pattern.match(text)
        if not match:
            continue
        extracted_action = action
        if extracted_action is None:
            extracted_action = match.groupdict().get("action")
        topic = _normalize_topic(match.group("topic"), extracted_action)
        if topic and any(term in topic for term in _health_context_terms):
            return topic
    return None


def apply_health_rules(context: RuleContext) -> Optional[RuleResult]:
    """健康领域指令匹配，覆盖监测、评估、医生咨询等。"""
    q = context.query
    person = extract_person_name(q)
    time_expr = extract_time_expression(q, context.base_time)
    has_medication_keyword = any(keyword in q for keyword in _medication_keywords)
    has_view_term = any(term in q for term in _medication_view_terms)
    has_view_verb = any(term in q for term in _medication_view_verbs)
    has_create_trigger = any(term in q for term in _medication_create_triggers)

    if has_view_term or ("提醒" in q and has_medication_keyword):
        if time_expr is not None or (has_create_trigger and not has_view_verb):
            medicine = extract_medicine(q)
            target_iso, event, status = derive_alarm_target(q, context.base_time, time_expr)
            time_text = time_expr.raw_text if time_expr and time_expr.raw_text else None
            return RuleResult(
                IntentCode.MEDICATION_REMINDER_CREATE,
                "新建用药提醒",
                target=medicine or "",
                event=event or (medicine or None),
                status=status,
                confidence=0.95,
                parsed_time=target_iso or None,
                time_text=time_text,
                time_confidence=0.9 if target_iso else None,
                time_source="rule" if target_iso else None,
            )
        return RuleResult(IntentCode.MEDICATION_REMINDER_VIEW, "用药提醒", target=person or "", confidence=0.95)

    profile_match = _profile_name_pattern.search(q)
    if profile_match:
        person = profile_match.group("name")

    if person and any(term in q for term in _health_profile_keywords):
        person = person.replace("了解", "").strip()
        for keyword in _health_profile_keywords:
            if keyword in person:
                person = person.replace(keyword, "").strip()
        person = person.strip("的 ")
        return RuleResult(IntentCode.HEALTH_PROFILE, "健康画像", target=person, confidence=0.95)

    knowledge_topic = _extract_health_knowledge_topic(q)
    if knowledge_topic:
        return RuleResult(IntentCode.HEALTH_EDUCATION, "健康科普", target=knowledge_topic, confidence=0.9)

    if any(keyword in q for keyword in _health_evaluation_keywords) or (
        "评估" in q and any(term in q for term in _health_evaluation_support_terms)
    ):
        if not any(metric in q for metric in _health_metric_map.keys()):
            return RuleResult(IntentCode.HEALTH_EVALUATION, "健康评估", target=person or "", confidence=0.95)

    if "健康监测" in q or "健康检测" in q:
        return RuleResult(IntentCode.HEALTH_MONITOR_GENERAL, "健康监测")

    for metric, (intent_code, result_text) in _health_metric_map.items():
        if metric in q:
            return RuleResult(intent_code, result_text, target=person or "", confidence=0.95)

    if "健康评估" in q:
        return RuleResult(IntentCode.HEALTH_EVALUATION, "健康评估", target=person or "")

    if "健康科普" in q or "科普" in q:
        return RuleResult(IntentCode.HEALTH_EDUCATION, "健康科普")

    if "健康画像" in q:
        sanitized_person = person or ""
        if sanitized_person:
            sanitized_person = sanitized_person.replace("了解", "").strip("的 ")
        return RuleResult(IntentCode.HEALTH_PROFILE, "健康画像", target=sanitized_person)

    if "小雅医生" in q or "健康咨询" in q:
        if person:
            return RuleResult(IntentCode.HEALTH_DOCTOR_SPECIFIC, "小雅医生", target=person)
        return RuleResult(IntentCode.HEALTH_DOCTOR_GENERAL, "小雅医生")

    if "名医问诊" in q or "远程问诊" in q:
        return RuleResult(IntentCode.HEALTH_SPECIALIST, "名医问诊")

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
    # 养生/健康操类内容归入教育/科普
    if any(term in context.query for term in _health_exercise_keywords):
        subject = extract_subject(context.query) or next(
            (term for term in _health_exercise_keywords if term in context.query),
            "",
        )
        return RuleResult(IntentCode.HEALTH_EDUCATION, "健康科普", target=subject, confidence=0.92)

    if ("学习" in context.query or "课程" in context.query or "教学" in context.query or
            re.search(r"(想|要|帮我).{0,2}学[\u4e00-\u9fa5A-Za-z0-9]{1,}", context.query)):
        subject = extract_subject(context.query)
        return RuleResult(IntentCode.EDUCATION_GENERAL, "小雅教育", target=subject or "")
    return None


def apply_entertainment_rule(context: RuleContext) -> Optional[RuleResult]:
    q = context.query
    prev_keywords = [
        "上一首",
        "上一曲",
        "上一个",
        "上一段",
        "上首",
        "上首歌",
        "上一首歌",
        "往前一首",
        "上一节",
    ]
    next_keywords = [
        "下一首",
        "下一曲",
        "下一个",
        "下一段",
        "下首",
        "下首歌",
        "下一首歌",
        "往后一首",
        "下一节",
    ]
    if any(term in q for term in prev_keywords):
        return RuleResult(IntentCode.ENTERTAINMENT_PREV_TRACK, "上一首")
    if any(term in q for term in next_keywords):
        return RuleResult(IntentCode.ENTERTAINMENT_NEXT_TRACK, "下一首")

    if any(keyword in q for keyword in _joke_keywords):
        return RuleResult(IntentCode.JOKE_MODE, "笑话模式", confidence=0.9)

    pause_triggers = ["暂停", "停止", "别放", "关掉", "停一下", "先别播", "关闭"]
    if any(trigger in q for trigger in pause_triggers):
        for term, intent in _entertainment_pause_map.items():
            if term in q:
                result_map = {
                    IntentCode.ENTERTAINMENT_MUSIC_OFF: "关闭音乐",
                    IntentCode.ENTERTAINMENT_AUDIOBOOK_OFF: "关闭听书",
                    IntentCode.ENTERTAINMENT_OPERA_OFF: "关闭戏曲",
                }
                return RuleResult(intent, result_map[intent], confidence=0.95)
        return RuleResult(IntentCode.ENTERTAINMENT_MUSIC_OFF, "关闭音乐", confidence=0.9)

    if any(keyword in q for keyword in _entertainment_resume_keywords):
        target = ""
        if any(term in q for term in ["戏曲", "曲艺"]):
            target = "戏曲"
        elif any(term in q for term in ["听书", "小说"]):
            target = "听书"
        elif "音乐" in q or "歌曲" in q:
            target = "音乐"
        return RuleResult(IntentCode.ENTERTAINMENT_RESUME, "继续播放", target=target)

    # 注意：“玩”在中文里很容易出现在“出去玩/去哪玩/适合去玩”等生活表达中，
    # 若直接以“玩”为触发词会导致天气/出行建议被误判为娱乐/游戏。
    if "斗地主" in q:
        return RuleResult(IntentCode.GAME_DOU_DI_ZHU, "斗地主")
    if any(term in q for term in ["象棋", "下象棋", "中国象棋", "围棋", "下棋"]):
        return RuleResult(IntentCode.GAME_CHINESE_CHESS, "中国象棋")
    if any(term in q for term in ["娱乐", "游戏"]):
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
    if any(term in q for term in _chat_strict_keywords):
        return RuleResult(IntentCode.CHAT, "语音陪伴或聊天", confidence=0.96)
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
    """提取学习/听类指令的目标内容，去除语气词与后缀。"""
    if not text:
        return None
    normalized = text.strip()
    learn_patterns = [
        r"(?:想要|希望|帮我|请)?(?:学习|学学|学)(?P<subject>[\u4e00-\u9fa5A-Za-z0-9\s]{1,20})",
        r"(?:想|要|希望|需要)?(?P<subject>[\u4e00-\u9fa5A-Za-z0-9\s]{2,20})(?:课程|教学|学习资料)",
    ]
    listen_patterns = [
        r"听(?P<subject>[\u4e00-\u9fa5A-Za-z0-9\s]{2,20})",
    ]
    trailing_tokens = [
        "一下下",
        "一下",
        "课程",
        "教学",
        "教程",
        "视频",
        "资料",
        "怎么做",
        "怎么写",
        "怎么说",
        "怎么练",
        "怎么学",
        "怎么",
        "如何",
        "吗",
        "呢",
        "呀",
        "啊",
        "吧",
        "么",
    ]

    def _clean_subject(raw: str) -> Optional[str]:
        candidate = raw.strip()
        candidate = candidate.replace(" ", "")
        for token in trailing_tokens:
            if candidate.endswith(token):
                candidate = candidate[: -len(token)]
        candidate = candidate.strip("的")
        candidate = re.split(r"[，。！？,.!?；;]", candidate)[0]
        generic_terms = {"东西", "事情", "事儿", "啥", "什么", "东西吗", "东西呀"}
        if len(candidate) >= 2 and candidate not in generic_terms:
            return candidate
        return None

    for pattern in learn_patterns:
        match = re.search(pattern, normalized)
        if match:
            subject = match.group("subject") or ""
            subject = _clean_subject(subject)
            if subject:
                return subject
    for pattern in listen_patterns:
        match = re.search(pattern, normalized)
        if match:
            subject = match.group("subject") or ""
            subject = _clean_subject(subject)
            if subject:
                return subject
    return None
