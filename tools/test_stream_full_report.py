#!/usr/bin/env python3
"""完整原始响应输出 — 全场景测试报告。"""
from __future__ import annotations

import json
import sys
import time
import httpx

BASE = "http://127.0.0.1:8765"
EP = f"{BASE}/api/command"

CASES = [
    # ── 非流式 ──
    {"name": "非流式-闹钟",         "p": {"query": "帮我设个明天早上6点的闹钟"}},
    {"name": "非流式-关闭音乐",     "p": {"query": "关闭音乐"}},
    {"name": "非流式-播报时间",     "p": {"query": "现在几点了"}},
    {"name": "非流式-天气查询",     "p": {"query": "今天长沙天气怎么样"}},
    {"name": "非流式-健康监测",     "p": {"query": "帮我测下血压"}},
    {"name": "非流式-你好",         "p": {"query": "你好"}},
    {"name": "非流式-不传stream",   "p": {"query": "帮我调高音量"}},
    {"name": "非流式-stream=false", "p": {"query": "帮我调低亮度", "stream": False}},
    {"name": "非流式-万年历",       "p": {"query": "今天农历多少号"}},
    {"name": "非流式-笑话",         "p": {"query": "讲个笑话"}},
    {"name": "非流式-健康科普",     "p": {"query": "高血压有什么注意事项"}},
    {"name": "非流式-息屏",         "p": {"query": "帮我息屏"}},
    # ── 流式 ──
    {"name": "流式-天气查询(长沙)",  "p": {"query": "今天长沙天气怎么样", "stream": True}},
    {"name": "流式-闹钟",           "p": {"query": "帮我设个明天早上7点的闹钟", "stream": True}},
    {"name": "流式-关闭音乐",       "p": {"query": "关闭音乐", "stream": True}},
    {"name": "流式-播报时间",       "p": {"query": "现在几点了", "stream": True}},
    {"name": "流式-健康监测",       "p": {"query": "帮我测一下血压", "stream": True}},
    {"name": "流式-你好",           "p": {"query": "你好", "stream": True}},
    {"name": "流式-调高音量",       "p": {"query": "声音调大一点", "stream": True}},
    {"name": "流式-万年历",         "p": {"query": "今天农历多少号", "stream": True}},
    {"name": "流式-笑话",           "p": {"query": "给我讲个笑话", "stream": True}},
    {"name": "流式-北京天气",       "p": {"query": "北京明天下不下雨", "stream": True}},
    {"name": "流式-息屏",           "p": {"query": "帮我息屏", "stream": True}},
    {"name": "流式-健康科普",       "p": {"query": "糖尿病饮食要注意什么", "stream": True}},
]

SEP = "─" * 88


def pretty_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def do_json(case):
    t0 = time.perf_counter()
    try:
        r = httpx.post(EP, json=case["p"], timeout=60)
        elapsed = time.perf_counter() - t0
        print(f"  HTTP {r.status_code}  ({elapsed:.2f}s)")
        if r.status_code == 200:
            body = r.json()
            print(pretty_json(body))
        else:
            print(f"  ERROR: {r.text}")
    except Exception as e:
        print(f"  EXCEPTION: {e}")


def do_sse(case):
    t0 = time.perf_counter()
    try:
        with httpx.stream("POST", EP, json=case["p"], timeout=60) as r:
            if r.status_code != 200:
                elapsed = time.perf_counter() - t0
                print(f"  HTTP {r.status_code}  ({elapsed:.2f}s)")
                return

            events = []
            cur_evt = ""
            cur_data = ""
            for line in r.iter_lines():
                if line.startswith("event: "):
                    cur_evt = line[7:]
                elif line.startswith("data: "):
                    cur_data = line[6:]
                elif line == "":
                    if cur_evt and cur_data:
                        events.append((cur_evt, cur_data))
                    cur_evt = ""
                    cur_data = ""

        elapsed = time.perf_counter() - t0
        print(f"  共 {len(events)} 个 SSE 事件  ({elapsed:.2f}s)")
        print()

        for i, (evt, data) in enumerate(events):
            if evt == "msg_delta":
                # delta 合并输出
                pass
            else:
                try:
                    obj = json.loads(data)
                    print(f"  [{evt}]")
                    print(f"  {pretty_json(obj)}")
                    print()
                except json.JSONDecodeError:
                    print(f"  [{evt}] {data}")
                    print()

        # 合并所有 delta 输出
        deltas = [d for e, d in events if e == "msg_delta"]
        if deltas:
            merged = ""
            for d in deltas:
                try:
                    obj = json.loads(d)
                    merged += obj.get("content", "")
                except json.JSONDecodeError:
                    merged += d
            print(f"  [msg_delta 合并] ({len(deltas)} 个片段)")
            print(f"  {merged}")
            print()

    except Exception as e:
        print(f"  EXCEPTION: {e}")


def main():
    print()
    print("=" * 88)
    print("  XY Assistant — 全场景完整响应报告")
    print("=" * 88)
    print()

    total = len(CASES)
    pass_count = 0

    for i, case in enumerate(CASES, 1):
        is_sse = case["p"].get("stream", False)
        tag = "SSE 流式" if is_sse else "JSON 非流式"
        print(SEP)
        print(f"  [{i}/{total}] {case['name']}  ({tag})")
        print(f"  请求: {json.dumps(case['p'], ensure_ascii=False)}")
        print(SEP)
        print()

        if is_sse:
            do_sse(case)
        else:
            do_json(case)

        print()
        pass_count += 1

    print("=" * 88)
    print(f"  完成: {pass_count}/{total}")
    print("=" * 88)


if __name__ == "__main__":
    main()
