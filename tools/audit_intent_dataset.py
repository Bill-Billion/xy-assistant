#!/usr/bin/env python3
"""
对生成的意图数据集进行统计与抽样审阅。

主要功能：
- 汇总各意图样本数及槽位覆盖情况；
- 随机抽取指定比例或固定数量的样本，打印到控制台供人工审核；
- 支持根据 intent_code 过滤。
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = BASE_DIR / "data" / "intent_dataset_v2.jsonl"

import sys

sys.path.append(str(BASE_DIR))


def load_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"数据集文件不存在: {path}")
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def summarize(entries: list[dict[str, Any]]) -> None:
    intent_counter = Counter()
    slot_counter: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for entry in entries:
        code = entry["intent_code"]
        intent_counter[code] += 1
        slots = entry.get("slots", {})
        for slot_key, slot_value in slots.items():
            if slot_value:
                slot_counter[code][slot_key] += 1
    print("=== 意图样本统计 ===")
    for code, count in intent_counter.most_common():
        print(f"{code:30s} {count:4d}")
        if slot_counter[code]:
            slot_info = ", ".join(f"{slot}:{slot_counter[code][slot]}" for slot in sorted(slot_counter[code]))
            print(f"   slots -> {slot_info}")


def sample_entries(
    entries: list[dict[str, Any]],
    ratio: float,
    absolute: int,
    rng: random.Random,
    intent_filter: set[str] | None = None,
) -> list[dict[str, Any]]:
    if intent_filter:
        entries = [entry for entry in entries if entry["intent_code"] in intent_filter]
    total = len(entries)
    if total == 0:
        return []
    if absolute > 0:
        sample_size = min(total, absolute)
    else:
        sample_size = max(1, int(total * ratio))
    return rng.sample(entries, sample_size)


def format_entry(entry: dict[str, Any]) -> str:
    lines = [
        f"- id: {entry.get('id')}",
        f"  intent: {entry['intent_code']} ({entry['result']})",
        f"  target: {entry.get('target', '')}",
        f"  event: {entry.get('event', '')}",
        f"  status: {entry.get('status', '')}",
        f"  confidence: {entry.get('confidence')}",
        f"  query: {entry['query']}",
    ]
    slots = entry.get("slots", {})
    if slots:
        slot_repr = ", ".join(f"{k}={v}" for k, v in slots.items() if v)
        if slot_repr:
            lines.append(f"  slots: {slot_repr}")
    history = entry.get("history") or []
    if history:
        lines.append("  history:")
        for turn in history:
            lines.append(f"    - {turn['role']}: {turn['content']}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="意图数据集抽样审核工具")
    parser.add_argument("--path", type=Path, default=DEFAULT_DATASET, help="数据集文件路径")
    parser.add_argument("--ratio", type=float, default=0.05, help="抽样比例，默认 5%")
    parser.add_argument("--count", type=int, default=0, help="抽样固定条数，优先级高于比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--intent", nargs="*", help="只抽取指定意图")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    entries = load_dataset(args.path)
    summarize(entries)
    intent_filter = set(args.intent) if args.intent else None
    sampled = sample_entries(entries, ratio=args.ratio, absolute=args.count, rng=rng, intent_filter=intent_filter)
    print("\n=== 抽样样本 ===")
    for item in sampled:
        print(format_entry(item))
        print("-" * 60)


if __name__ == "__main__":
    main()
