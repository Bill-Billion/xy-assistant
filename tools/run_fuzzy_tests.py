from __future__ import annotations

import asyncio
import csv
import json
import re
import sys
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict


API_URL = "http://0.0.0.0:8000/api/command"
INPUT_FILE = Path("order_fuzzy.csv")
OUTPUT_FILE = Path("order_fuzzy_results.csv")
ENCODING = "utf-8-sig"
TIMEOUT = 20

# 兼容以脚本方式运行（python tools/run_fuzzy_tests.py），确保可导入项目包 app/*
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_FORCE_LOCAL = False


async def _call_local(query: str, *, session_id: str) -> Dict[str, str]:
    """在无法发起 HTTP 请求（如沙箱限制）时，直接在进程内调用服务以生成结果。"""
    from app.core.config import get_settings
    from app.schemas.request import CommandRequest
    from app.services.command_service import CommandService
    from app.services.conversation import ConversationManager
    from app.services.intent_classifier import IntentClassifier

    class _NoopLLMClient:
        """离线兜底：不请求外部网络，直接返回空结果供规则层接管。"""

        async def chat(  # noqa: D401
            self,
            *,
            system_prompt: str,
            messages: list[dict[str, str]],
            response_format: dict[str, Any] | None = None,
            overrides: dict[str, Any] | None = None,
        ) -> tuple[str, dict[str, Any]]:
            return "", {}

    if not hasattr(_call_local, "_service"):
        settings = get_settings()
        classifier = IntentClassifier(_NoopLLMClient(), confidence_threshold=settings.confidence_threshold)
        manager = ConversationManager()
        # 说明：离线模式下不生成 LLM 话术，不调用天气/播报外部接口，仅验证意图与规则是否符合预期。
        service = CommandService(
            intent_classifier=classifier,
            conversation_manager=manager,
            settings=settings,
            weather_service=None,
            weather_broadcast_generator=None,
            reply_llm_client=None,
        )
        setattr(_call_local, "_service", service)

    service: CommandService = getattr(_call_local, "_service")
    try:
        response = await service.handle_command(CommandRequest(sessionId=session_id, query=query))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "msg": f"(本地调用异常){exc}",
            "result": "",
        }

    function_analysis = getattr(response, "function_analysis", None)
    result = ""
    target = ""
    if function_analysis is not None:
        result = str(getattr(function_analysis, "result", "") or "")
        target = str(getattr(function_analysis, "target", "") or "")
    return {
        "status": "local",
        "msg": str(getattr(response, "msg", "") or ""),
        "result": result,
        "target": target,
    }


def call_api(query: str, *, session_id: str) -> Dict[str, str]:
    from urllib.parse import urlparse

    global _FORCE_LOCAL
    if _FORCE_LOCAL:
        return asyncio.run(_call_local(query, session_id=session_id))

    parsed = urlparse(API_URL)
    host = parsed.hostname or "0.0.0.0"
    port = parsed.port or 80
    path = parsed.path or "/"

    body = json.dumps({"query": query, "sessionId": session_id}, ensure_ascii=False).encode("utf-8")

    conn = HTTPConnection(host, port, timeout=TIMEOUT)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        if resp.status >= 400:
            return {
                "status": str(resp.status),
                "msg": f"HTTP {resp.status}: {data}",
                "result": "",
            }
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return {
                "status": str(resp.status),
                "msg": f"(解析失败){data}",
                "result": "",
            }
        msg = str(payload.get("msg") or "")
        function_analysis = payload.get("function_analysis") or {}
        result = str(function_analysis.get("result") or "")
        target = str(function_analysis.get("target") or "")
        return {
            "status": str(resp.status),
            "msg": msg,
            "result": result,
            "target": target,
        }
    except Exception as exc:  # noqa: BLE001
        # 沙箱环境可能禁止本地 HTTP 连接（Errno 1: Operation not permitted），此时退化为本地调用
        errno = getattr(exc, "errno", None)
        if isinstance(exc, (PermissionError, OSError)) and errno == 1:
            _FORCE_LOCAL = True
            return asyncio.run(_call_local(query, session_id=session_id))
        return {
            "status": "error",
            "msg": f"(接口异常){exc}",
            "result": "",
            "target": "",
        }
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _split_spec(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[|｜]", raw or "") if item.strip()]


def judge(row: Dict[str, str], api_result: Dict[str, str]) -> str:
    expected_clean = (row.get("预期功能") or "").strip()
    actual_clean = (api_result.get("result") or "").strip()
    msg_clean = (api_result.get("msg") or "").strip()
    mode = (row.get("校验模式") or "").strip() or "result_exact"
    candidate_results = _split_spec(row.get("预期功能候选", ""))
    msg_keywords = _split_spec(row.get("预期msg关键词", ""))

    if mode == "msg_only":
        if actual_clean:
            return "❌ 不匹配"
        if not msg_clean:
            return "失败：未返回结果"
        if msg_keywords and not any(keyword in msg_clean for keyword in msg_keywords):
            return "❌ 不匹配"
        return "✅ 完全匹配"

    if mode == "clarify":
        if actual_clean:
            return "❌ 不匹配"
        if not msg_clean:
            return "失败：未返回结果"
        if msg_keywords and not any(keyword in msg_clean for keyword in msg_keywords):
            return "❌ 不匹配"
        return "✅ 完全匹配"

    if mode == "result_in":
        expected_set = [expected_clean, *candidate_results] if expected_clean else candidate_results
        if not actual_clean:
            return "失败：未返回结果"
        if actual_clean in expected_set:
            return "✅ 完全匹配"
        if any(actual_clean in expected or expected in actual_clean for expected in expected_set):
            return "⚠️ 部分匹配"
        return "❌ 不匹配"

    if expected_clean == "" and actual_clean == "":
        return "✅ 完全匹配"
    if expected_clean == "" and actual_clean:
        return "❌ 不匹配"
    if not actual_clean:
        return "失败：未返回结果"
    if expected_clean == actual_clean:
        return "✅ 完全匹配"
    if expected_clean in actual_clean or actual_clean in expected_clean:
        return "⚠️ 部分匹配"
    return "❌ 不匹配"


def main() -> None:
    global API_URL
    if len(sys.argv) >= 3 and sys.argv[1] == "--endpoint":
        API_URL = sys.argv[2].strip() or API_URL

    if not INPUT_FILE.exists():
        raise SystemExit("order_fuzzy.csv 不存在，请先生成。")

    with INPUT_FILE.open(encoding=ENCODING) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fieldnames = list(reader.fieldnames or []) + ["输出msg", "输出result", "输出target", "接口状态", "匹配判断"]

    results = []
    for idx, row in enumerate(rows, 1):
        command = row.get("模糊指令", "").strip()
        expected = row.get("预期功能", "").strip()
        api_result = call_api(command, session_id=f"fuzzy-{idx}")
        row["输出msg"] = api_result["msg"]
        row["输出result"] = api_result["result"]
        row["输出target"] = api_result.get("target", "")
        row["接口状态"] = api_result["status"]
        row["匹配判断"] = judge(row, api_result)
        results.append(row)

    with OUTPUT_FILE.open("w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    summary = {
        "total": len(results),
        "matched": sum(1 for r in results if r["匹配判断"].startswith("✅")),
        "partial": sum(1 for r in results if r["匹配判断"].startswith("⚠️")),
        "failed": sum(1 for r in results if r["匹配判断"].startswith("❌")),
        "error": sum(1 for r in results if r["匹配判断"].startswith("失败")),
        "output_file": str(OUTPUT_FILE),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
