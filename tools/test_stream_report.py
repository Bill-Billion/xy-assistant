#!/usr/bin/env python3
"""SSE 流式输出 + 非流式全场景真实测试脚本。

启动服务后执行:
    python tools/test_stream_report.py
"""
from __future__ import annotations

import json
import sys
import time
import httpx

BASE = "http://127.0.0.1:8765"
ENDPOINT = f"{BASE}/api/command"

# ── 测试用例 ──────────────────────────────────────────────────────────

TEST_CASES: list[dict] = [
    # ─── 非流式（向后兼容）───
    {"name": "非流式-闹钟",           "payload": {"query": "帮我设个明天早上6点的闹钟"}},
    {"name": "非流式-关闭音乐",       "payload": {"query": "关闭音乐"}},
    {"name": "非流式-播报时间",       "payload": {"query": "现在几点了"}},
    {"name": "非流式-天气查询",       "payload": {"query": "今天长沙天气怎么样"}},
    {"name": "非流式-健康监测",       "payload": {"query": "帮我测下血压"}},
    {"name": "非流式-你好(闲聊)",     "payload": {"query": "你好"}},
    {"name": "非流式-不传stream",     "payload": {"query": "帮我调高音量"}},
    {"name": "非流式-stream=false",   "payload": {"query": "帮我调低亮度", "stream": False}},
    {"name": "非流式-万年历",         "payload": {"query": "今天农历多少号"}},
    {"name": "非流式-笑话",           "payload": {"query": "讲个笑话"}},
    {"name": "非流式-健康科普",       "payload": {"query": "高血压有什么注意事项"}},
    {"name": "非流式-息屏",           "payload": {"query": "帮我息屏"}},

    # ─── 流式（SSE）───
    {"name": "流式-天气查询",         "payload": {"query": "今天长沙天气怎么样", "stream": True}},
    {"name": "流式-闹钟",             "payload": {"query": "帮我设个明天早上7点的闹钟", "stream": True}},
    {"name": "流式-关闭音乐",         "payload": {"query": "关闭音乐", "stream": True}},
    {"name": "流式-播报时间",         "payload": {"query": "现在几点了", "stream": True}},
    {"name": "流式-健康监测",         "payload": {"query": "帮我测一下血压", "stream": True}},
    {"name": "流式-你好(闲聊)",       "payload": {"query": "你好", "stream": True}},
    {"name": "流式-调高音量",         "payload": {"query": "声音调大一点", "stream": True}},
    {"name": "流式-万年历",           "payload": {"query": "今天农历多少号", "stream": True}},
    {"name": "流式-笑话",             "payload": {"query": "给我讲个笑话", "stream": True}},
    {"name": "流式-北京天气",         "payload": {"query": "北京明天下不下雨", "stream": True}},
    {"name": "流式-息屏",             "payload": {"query": "帮我息屏", "stream": True}},
    {"name": "流式-健康科普",         "payload": {"query": "糖尿病饮食要注意什么", "stream": True}},
]


# ── 工具函数 ──────────────────────────────────────────────────────────

def run_non_stream(case: dict) -> dict:
    """非流式测试：普通 POST，期望 JSON 响应。"""
    t0 = time.perf_counter()
    try:
        resp = httpx.post(ENDPOINT, json=case["payload"], timeout=30)
        elapsed = round(time.perf_counter() - t0, 2)
        if resp.status_code != 200:
            return {"ok": False, "elapsed": elapsed, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        body = resp.json()
        return {
            "ok": True,
            "elapsed": elapsed,
            "code": body.get("code"),
            "msg": (body.get("msg") or "")[:120],
            "result": (body.get("function_analysis") or {}).get("result", ""),
            "sessionId": body.get("sessionId", "")[:12],
        }
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 2)
        return {"ok": False, "elapsed": elapsed, "error": str(e)[:200]}


def run_stream(case: dict) -> dict:
    """流式测试：读取 SSE 事件流，校验事件序列。"""
    t0 = time.perf_counter()
    events: list[dict] = []
    raw_chunks: list[str] = []
    try:
        with httpx.stream("POST", ENDPOINT, json=case["payload"], timeout=30) as resp:
            if resp.status_code != 200:
                elapsed = round(time.perf_counter() - t0, 2)
                return {"ok": False, "elapsed": elapsed, "error": f"HTTP {resp.status_code}"}
            current_event = ""
            current_data = ""
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    current_event = line[7:]
                elif line.startswith("data: "):
                    current_data = line[6:]
                elif line == "":
                    if current_event and current_data:
                        try:
                            parsed = json.loads(current_data)
                        except json.JSONDecodeError:
                            parsed = current_data
                        events.append({"event": current_event, "data": parsed})
                        if current_event == "msg_delta" and isinstance(parsed, dict):
                            raw_chunks.append(parsed.get("content", ""))
                    current_event = ""
                    current_data = ""
        elapsed = round(time.perf_counter() - t0, 2)
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 2)
        return {"ok": False, "elapsed": elapsed, "error": str(e)[:200]}

    event_types = [e["event"] for e in events]
    streamed_msg = "".join(raw_chunks)

    # 分析事件序列
    has_meta = "meta" in event_types
    has_done = "done" in event_types
    has_error = "error" in event_types
    delta_count = event_types.count("msg_delta")

    # done 事件中的最终 msg
    done_msg = ""
    done_result = ""
    done_session = ""
    for e in events:
        if e["event"] == "done" and isinstance(e["data"], dict):
            done_msg = (e["data"].get("msg") or "")[:120]
            done_result = (e["data"].get("function_analysis") or {}).get("result", "")
            done_session = (e["data"].get("sessionId") or "")[:12]

    # meta 事件中的 function_analysis
    meta_result = ""
    for e in events:
        if e["event"] == "meta" and isinstance(e["data"], dict):
            meta_result = (e["data"].get("function_analysis") or {}).get("result", "")

    ok = (has_meta or has_done) and not has_error
    return {
        "ok": ok,
        "elapsed": elapsed,
        "event_sequence": " → ".join(
            f"{t}(x{event_types.count(t)})" if event_types.count(t) > 1 else t
            for t in dict.fromkeys(event_types)
        ),
        "delta_count": delta_count,
        "meta_result": meta_result,
        "done_result": done_result,
        "streamed_msg": streamed_msg[:80],
        "done_msg": done_msg,
        "sessionId": done_session,
        "has_error": has_error,
        "error_detail": next(
            (e["data"] for e in events if e["event"] == "error"), None
        ),
    }


# ── 主流程 ────────────────────────────────────────────────────────────

def main():
    print("=" * 90)
    print("  XY Assistant — SSE 流式输出全场景测试报告")
    print("=" * 90)

    # 先检查服务是否可达
    try:
        r = httpx.get(f"{BASE}/docs", timeout=5)
        assert r.status_code == 200
    except Exception:
        print("\n  ❌  服务不可达，请先启动: uvicorn app.main:app --port 8765\n")
        sys.exit(1)

    results: list[dict] = []
    total = len(TEST_CASES)

    for i, case in enumerate(TEST_CASES, 1):
        is_stream = case["payload"].get("stream", False)
        tag = "SSE" if is_stream else "JSON"
        print(f"\n[{i}/{total}] [{tag}] {case['name']} — query: {case['payload']['query']}")

        if is_stream:
            r = run_stream(case)
        else:
            r = run_non_stream(case)

        r["name"] = case["name"]
        r["query"] = case["payload"]["query"]
        r["mode"] = tag
        results.append(r)

        status = "PASS" if r["ok"] else "FAIL"
        print(f"       {status}  ({r['elapsed']}s)")
        if not r["ok"]:
            print(f"       error: {r.get('error') or r.get('error_detail')}")
        else:
            if is_stream:
                print(f"       events: {r['event_sequence']}")
                print(f"       delta_count: {r['delta_count']}, meta_result: {r.get('meta_result','')}")
                if r.get("streamed_msg"):
                    print(f"       streamed: {r['streamed_msg']}...")
                if r.get("done_msg"):
                    print(f"       done_msg: {r['done_msg']}")
            else:
                print(f"       result: {r.get('result','')}, msg: {r.get('msg','')}")

    # ── 汇总 ──
    passed = sum(1 for r in results if r["ok"])
    failed = sum(1 for r in results if not r["ok"])

    print("\n")
    print("=" * 90)
    print("  汇总")
    print("=" * 90)
    print(f"  总计: {total}    通过: {passed}    失败: {failed}")
    print()

    # 分类汇总
    for mode in ["JSON", "SSE"]:
        subset = [r for r in results if r["mode"] == mode]
        if not subset:
            continue
        p = sum(1 for r in subset if r["ok"])
        f = sum(1 for r in subset if not r["ok"])
        print(f"  [{mode}]  通过: {p}/{len(subset)}  失败: {f}/{len(subset)}")
        for r in subset:
            status = "PASS" if r["ok"] else "FAIL"
            line = f"    {status}  {r['name']:<24} ({r['elapsed']}s)"
            if mode == "SSE" and r["ok"]:
                line += f"  deltas={r.get('delta_count',0)}"
            if not r["ok"]:
                line += f"  err={r.get('error','')[:60]}"
            print(line)
        print()

    if failed > 0:
        print("  ⚠  有失败用例，请检查上方详细输出。")
    else:
        print("  ✅  全部通过！")
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
