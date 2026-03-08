#!/usr/bin/env python3
"""
批量生成带标注的意图数据集。

核心特点：
- 从 data/intent_templates.yaml 中读取模板配置，覆盖多意图场景；
- 支持变量组合、礼貌前后缀、错别字/口语噪声注入，提升语料多样性；
- 生成目标字段、槽位字段时自动解析时间表达、相对偏移；
- 写入 JSONL，并在控制台输出统计信息；
- 对每条数据做严格校验，确保 result/target/slots 等符合需求约束；
- 记录生成来源（模板、变体哈希）便于回溯与抽检。
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import sys

import dateparser
import yaml
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from app.services.intent_definitions import INTENT_DEFINITIONS, IntentCode
from app.services.prompt_templates import get_allowed_results

TEMPLATES_PATH = BASE_DIR / "data" / "intent_templates.yaml"
OUTPUT_PATH = BASE_DIR / "data" / "intent_dataset_v2.jsonl"
TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIDENCE = 0.9
DEFAULT_LIMIT = 40

POLITE_SUFFIXES = ["好吗？", "可以吗？", "谢谢。", "谢谢~"]
HELP_SYNONYMS = ["帮我", "麻烦", "劳烦", "请帮忙", "请"]
RELATIVE_OFFSET_MAP = {
    "十分钟后": "+0d0h10m",
    "十五分钟后": "+0d0h15m",
    "二十分钟后": "+0d0h20m",
    "半小时后": "+0d0h30m",
    "一小时后": "+0d1h0m",
    "一个小时后": "+0d1h0m",
    "两个小时后": "+0d2h0m",
    "两小时后": "+0d2h0m",
}
TYPO_MAP = {
    "闹钟": ["闹鐘", "鬧钟"],
    "提醒": ["提请", "提示"],
    "医生": ["醫生", "医生儿"],
    "视频": ["視頻", "视频儿"],
    "天气": ["天气儿", "天气呢"],
}
CHINESE_NUMERAL_MAP = {
    "零": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}
DATE_ALIASES = {
    "本周五": "this friday",
    "本周日": "this sunday",
    "这个周末": "this weekend",
    "周末": "this weekend",
    "下周三": "next wednesday",
    "下周一": "next monday",
    "国庆那天": "10月1日",
    "农历九月初十": "2025年10月12日",
    "农历九月初十的天气": "2025年10月12日",
}
WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class TemplateConfigError(RuntimeError):
    """Raised when template configuration is invalid."""


def load_templates(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    if not isinstance(data, dict):
        raise TemplateConfigError("模板配置根节点必须为字典")
    return data


def iter_variant_mappings(vary_cfg: dict[str, list[Any]], max_variants: int | None, rng: random.Random) -> Iterable[dict[str, Any]]:
    if not vary_cfg:
        yield {}
        return
    keys = list(vary_cfg.keys())
    pools = []
    for key in keys:
        values = vary_cfg[key]
        if not isinstance(values, list) or not values:
            raise TemplateConfigError(f"变量 {key} 必须配置非空列表")
        pools.append(values)
    all_variants = list(itertools.product(*pools))
    rng.shuffle(all_variants)
    if max_variants is not None:
        all_variants = all_variants[:max_variants]
    for combo in all_variants:
        mapping: dict[str, Any] = {}
        for key, value in zip(keys, combo):
            if isinstance(value, dict):
                mapping.update(value)
            else:
                mapping[key] = value
        yield mapping


def try_parse_weekday_phrase(text: str, base_time: datetime) -> tuple[str, bool] | None:
    lowered = text.lower()
    if lowered in {"this weekend"}:
        # 默认周六
        target_weekday = 5
        days_ahead = (target_weekday - base_time.weekday()) % 7
        target_date = (base_time + timedelta(days=days_ahead)).date()
        return target_date.strftime("%Y-%m-%d"), False
    match = re.match(
        r"(?P<prefix>this|next)\s+(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?P<time>\d{1,2}:\d{2}))?$",
        lowered,
    )
    if not match:
        return None
    prefix = match.group("prefix")
    weekday = WEEKDAY_MAP[match.group("weekday")]
    time_part = match.group("time")
    days_ahead = (weekday - base_time.weekday()) % 7
    if prefix == "next":
        days_ahead = days_ahead + (0 if days_ahead > 0 else 7)
    target_datetime = base_time + timedelta(days=days_ahead)
    if time_part:
        hour, minute = [int(part) for part in time_part.split(":")]
        target_datetime = target_datetime.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_datetime.strftime("%Y-%m-%d %H:%M:%S"), True
    return target_datetime.date().strftime("%Y-%m-%d"), False


def resolve_time_expr(expr: str, variant_map: dict[str, Any], base_time: datetime) -> str:
    formatted = expr.format(**variant_map)
    formatted = DATE_ALIASES.get(formatted, formatted)
    for cn, digit in CHINESE_NUMERAL_MAP.items():
        formatted = formatted.replace(cn, digit)
    manual = try_parse_weekday_phrase(formatted, base_time)
    if manual:
        value, has_time = manual
        return value if has_time else value
    parsed = dateparser.parse(
        formatted,
        settings={
            "TIMEZONE": "Asia/Shanghai",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": base_time,
            "PREFER_DATES_FROM": "future",
            "PREFER_DAY_OF_MONTH": "current",
        },
    )
    if parsed is None:
        raise TemplateConfigError(f"无法解析时间表达式: {formatted}")
    parsed = parsed.astimezone(TIMEZONE)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def resolve_relative_offset(description: str, variant_map: dict[str, Any]) -> str:
    normalized = description.format(**variant_map)
    normalized = normalized.strip()
    if normalized in RELATIVE_OFFSET_MAP:
        return RELATIVE_OFFSET_MAP[normalized]
    # 兜底：尝试解析成时间差
    parsed = dateparser.parse(
        normalized,
        settings={
            "TIMEZONE": "Asia/Shanghai",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
        languages=["zh"],
    )
    if parsed:
        now = datetime.now(TIMEZONE)
        delta: timedelta = parsed - now
        days = max(0, int(delta.days))
        hours = max(0, int(delta.seconds // 3600))
        minutes = max(0, int((delta.seconds % 3600) // 60))
        return f"+{days}d{hours}h{minutes}m"
    raise TemplateConfigError(f"无法解析相对时间: {normalized}")


def maybe_augment_query(query: str, rng: random.Random) -> str:
    augmented = query
    if rng.random() < 0.35:
        augmented = augmented.replace("帮我", rng.choice(HELP_SYNONYMS))
    if rng.random() < 0.15 and len(augmented) < 30:
        suffix = rng.choice(POLITE_SUFFIXES)
        if not augmented.endswith(("？", "。", "！", "~")):
            augmented += suffix
        else:
            augmented = augmented.rstrip("？。！~") + suffix
    if rng.random() < 0.1:
        for token, variants in TYPO_MAP.items():
            if token in augmented and rng.random() < 0.4:
                augmented = augmented.replace(token, rng.choice(variants), 1)
    return augmented


def format_value(value: Any, variant_map: dict[str, Any], base_time: datetime) -> Any:
    if isinstance(value, str):
        return value.format(**variant_map)
    if isinstance(value, dict) and "expr" in value:
        expr = value["expr"]
        return resolve_time_expr(expr, variant_map, base_time)
    return value


def merge_slots(base_slots: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base_slots)
    if overrides:
        for key, value in overrides.items():
            if key == "slots" and isinstance(value, dict):
                merged.update(value)
            else:
                merged[key] = value
    return merged


def prepare_entry(
    intent_code: str,
    template_id: str,
    variant_index: int,
    template_cfg: dict[str, Any],
    intent_cfg: dict[str, Any],
    variant_map: dict[str, Any],
    base_time: datetime,
    rng: random.Random,
) -> dict[str, Any]:
    definition = INTENT_DEFINITIONS[IntentCode(intent_code)]
    base_fields = intent_cfg.get("base", {}).get("fields", {}) or {}
    template_fields = template_cfg.get("fields", {}) or {}

    base_slots = intent_cfg.get("base", {}).get("slots", {}) or {}
    template_slots = template_cfg.get("slots", {}) or {}

    fields: dict[str, Any] = dict(base_fields)
    slots: dict[str, Any] = dict(base_slots)

    def apply_fields(source: dict[str, Any]) -> None:
        for key, value in source.items():
            if key == "slots":
                for slot_key, slot_val in (value or {}).items():
                    slots[slot_key] = format_value(slot_val, variant_map, base_time)
                continue
            if key in {"time_iso_expr", "target_expr", "relative_target"}:
                formatted = format_value(value, variant_map, base_time)
                if key == "time_iso_expr":
                    slots["time_iso"] = resolve_time_expr(formatted, variant_map, base_time)
                elif key == "target_expr":
                    fields["target"] = resolve_time_expr(formatted, variant_map, base_time)
                    slots.setdefault("time_iso", fields["target"])
                elif key == "relative_target":
                    offset = resolve_relative_offset(formatted, variant_map)
                    fields["target"] = offset
                    slots.setdefault("relative_offset", offset)
                continue
            fields[key] = format_value(value, variant_map, base_time)

    apply_fields(base_fields)
    apply_fields(template_fields)

    for slot_key, slot_value in merge_slots(base_slots, template_slots).items():
        slots[slot_key] = format_value(slot_value, variant_map, base_time)

    intent_result = definition.result
    result = fields.pop("result", intent_result)
    confidence = float(fields.pop("confidence", DEFAULT_CONFIDENCE))

    entry = {
        "intent_code": intent_code,
        "result": result,
        "target": fields.pop("target", ""),
        "event": fields.pop("event", ""),
        "status": fields.pop("status", ""),
        "confidence": round(confidence, 3),
        "clarify_required": bool(fields.pop("clarify_required", False)),
        "clarify_message": fields.pop("clarify_message", None),
        "slots": slots,
        "fields": fields,  # 记录剩余字段（例如 advice/safety 等）
        "meta": {
            "template_id": template_id,
            "variant_index": variant_index,
        },
    }

    history_candidates = template_cfg.get("history") or intent_cfg.get("histories") or []
    if history_candidates:
        entry["history"] = rng.choice(history_candidates)
    else:
        entry["history"] = []

    query_template = template_cfg["text"]
    formatted_query = query_template.format(**variant_map)
    entry["query"] = maybe_augment_query(formatted_query.strip(), rng)
    return entry


def validate_entry(entry: dict[str, Any], allowed_results: set[str]) -> None:
    intent_code = entry["intent_code"]
    if intent_code not in INTENT_DEFINITIONS:
        raise TemplateConfigError(f"未知意图: {intent_code}")
    expected_result = INTENT_DEFINITIONS[IntentCode(intent_code)].result
    if entry["result"] != expected_result and entry["result"] not in allowed_results:
        raise TemplateConfigError(f"{intent_code} result 非法: {entry['result']}")
    if not isinstance(entry["query"], str) or not entry["query"]:
        raise TemplateConfigError(f"{intent_code} 缺少 query")
    if not (0.0 <= entry["confidence"] <= 1.0):
        raise TemplateConfigError(f"{intent_code} 置信度越界: {entry['confidence']}")
    slots = entry.get("slots", {})
    if not isinstance(slots, dict):
        raise TemplateConfigError(f"{intent_code} slots 应为字典")
    for key, value in slots.items():
        if value in (None, ""):
            continue
        if key in {"time_iso"}:
            parsed = dateparser.parse(value, settings={"TIMEZONE": "Asia/Shanghai"})
            if not parsed:
                raise TemplateConfigError(f"{intent_code} time_iso 无法解析: {value}")
        elif key == "relative_offset":
            if not re.fullmatch(r"\+?\d+d\d+h\d+m", value):
                raise TemplateConfigError(f"{intent_code} relative_offset 非法: {value}")
        elif not isinstance(value, str):
            raise TemplateConfigError(f"{intent_code} slots[{key}] 必须为字符串")


def write_dataset(entries: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for item in entries:
            record = dict(item)
            record.pop("fields", None)  # fields 仅用于生成阶段，不落库
            json.dump(record, fp, ensure_ascii=False)
            fp.write("\n")


def generate_dataset(seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    templates_cfg = load_templates(TEMPLATES_PATH)
    allowed_results = get_allowed_results()
    base_time = datetime.now(TIMEZONE)

    all_entries: list[dict[str, Any]] = []
    for intent_code, intent_cfg in templates_cfg.items():
        if intent_code not in INTENT_DEFINITIONS:
            raise TemplateConfigError(f"模板包含未知意图: {intent_code}")
        limit = int(intent_cfg.get("limit", DEFAULT_LIMIT))
        variants: list[dict[str, Any]] = []
        templates = intent_cfg.get("templates", [])
        if not templates:
            raise TemplateConfigError(f"{intent_code} 未配置任何模板")
        variant_counter = 0
        for template_cfg in templates:
            template_id = template_cfg.get("id", f"{intent_code.lower()}_{variant_counter}")
            vary_cfg = template_cfg.get("vary", {})
            max_variants = template_cfg.get("max_variants")
            for mapping in iter_variant_mappings(vary_cfg, max_variants, rng):
                variant_counter += 1
                entry = prepare_entry(
                    intent_code=intent_code,
                    template_id=template_id,
                    variant_index=variant_counter,
                    template_cfg=template_cfg,
                    intent_cfg=intent_cfg,
                    variant_map=mapping,
                    base_time=base_time,
                    rng=rng,
                )
                validate_entry(entry, allowed_results)
                variants.append(entry)
        rng.shuffle(variants)
        if len(variants) > limit:
            variants = variants[:limit]
        # 加编号
        for idx, entry in enumerate(variants, start=1):
            entry["id"] = f"{intent_code.lower()}_{idx:03d}"
        all_entries.extend(variants)
    return all_entries


def summarize(entries: list[dict[str, Any]]) -> None:
    counter = Counter(entry["intent_code"] for entry in entries)
    print(f"生成样本总数：{len(entries)}")
    for intent_code, count in counter.most_common():
        print(f"{intent_code:30s} {count:4d}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成意图识别训练数据")
    parser.add_argument("--seed", type=int, default=2025, help="随机种子，默认 2025")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="输出 JSONL 路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = generate_dataset(seed=args.seed)
    write_dataset(entries, args.output)
    summarize(entries)
    print(f"数据已写入 {args.output}")


if __name__ == "__main__":
    main()
