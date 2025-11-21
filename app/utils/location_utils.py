from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

_TIME_TOKENS = [
    "今天",
    "明天",
    "后天",
    "这周",
    "本周",
    "下周",
    "这星期",
    "本星期",
    "下星期",
    "这礼拜",
    "本礼拜",
    "下礼拜",
]
_TRAILING_TOKENS = ["需要", "要", "得", "吗", "呢", "嘛", "吧", "是", "呀", "啊"]

_NUMERIC_PATTERN = re.compile(r"\d")
_QUESTION_PATTERN = re.compile(r"(什么|哪儿|哪里|哪|多少|是否|啥|嘛|吗|呀|啊)")

_CITY_FROM_QUERY_PATTERNS = [
    re.compile(r"(?:去|到|前往|准备去|想去|计划去)(?P<city>[\u4e00-\u9fa5]{2,7}?)(?:市|省|自治区|州|县|区)?(?=\s|$|[，。！？,.!?]|需要|要|得|吗|呢|嘛|吧)"),
    re.compile(r"(?P<city>[\u4e00-\u9fa5]{2,7})(?:市|省|自治区|州|县|区)?(?:的)?天气"),
]


def _data_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "cities.json"


@lru_cache(maxsize=1)
def _load_city_map() -> Dict[str, str]:
    data_file = _data_path()
    mapping: Dict[str, str] = {}
    if data_file.exists():
        try:
            raw = json.loads(data_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        cities = raw.get("cities") if isinstance(raw, dict) else raw
        if isinstance(cities, list):
            for item in cities:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not name:
                    continue
                mapping[name] = name
                for alias in item.get("aliases", []) or []:
                    if isinstance(alias, str):
                        mapping[alias] = name
    return mapping


def _clean_city_text(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    for token in _TIME_TOKENS:
        cleaned = cleaned.replace(token, "")
    cleaned = cleaned.replace("市市", "市")
    cleaned = re.sub(r"[\s，。！？,.!?:：]", "", cleaned)
    cleaned = re.sub(r"(天气|气温|气候|情况)", "", cleaned)
    for token in _TRAILING_TOKENS:
        if cleaned.endswith(token):
            cleaned = cleaned[: -len(token)]
    cleaned = cleaned.replace("是什么", "")
    cleaned = cleaned.replace("是什么时候", "")
    cleaned = cleaned.replace("什么", "")
    return cleaned.strip()


def normalize_city_name(raw: str, default_city: str) -> Tuple[str, str]:
    cleaned = _clean_city_text(raw)
    if not cleaned:
        return default_city, "empty"

    city_map = _load_city_map()
    if cleaned in city_map:
        return city_map[cleaned], "match"
    stripped = cleaned[:-1] if cleaned.endswith("市") else cleaned
    if stripped in city_map:
        return city_map[stripped], "match"

    if _NUMERIC_PATTERN.search(cleaned):
        return default_city, "numeric"
    if len(cleaned) <= 2 and cleaned.endswith("市"):
        return default_city, "short"
    if _QUESTION_PATTERN.search(cleaned):
        return default_city, "question"

    return cleaned, "raw"


def extract_city_from_query(text: str, default_city: str) -> Tuple[str | None, str]:
    if not text:
        return None, "empty"
    for pattern in _CITY_FROM_QUERY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group("city")
        normalized, reason = normalize_city_name(candidate + "市", default_city)
        if normalized and reason not in {"raw", "numeric", "short"}:
            return normalized, reason
    city_map = _load_city_map()
    for alias, official in sorted(city_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and alias in text:
            normalized, reason = normalize_city_name(alias, default_city)
            if normalized:
                return normalized, f"substring:{reason}"
    return None, "not_found"
