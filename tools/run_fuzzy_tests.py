from __future__ import annotations

import csv
import json
from http.client import HTTPConnection
from pathlib import Path
from typing import Dict


API_URL = "http://0.0.0.0:8000/api/command"
INPUT_FILE = Path("order_fuzzy.csv")
OUTPUT_FILE = Path("order_fuzzy_results.csv")
ENCODING = "utf-8-sig"
TIMEOUT = 20


def call_api(query: str) -> Dict[str, str]:
    from urllib.parse import urlparse

    parsed = urlparse(API_URL)
    host = parsed.hostname or "0.0.0.0"
    port = parsed.port or 80
    path = parsed.path or "/"

    body = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")

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
        return {
            "status": str(resp.status),
            "msg": msg,
            "result": result,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "msg": f"(接口异常){exc}",
            "result": "",
        }
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def judge(expected: str, actual: str) -> str:
    expected_clean = expected.strip()
    actual_clean = actual.strip()
    if not actual_clean:
        return "失败：未返回结果"
    if expected_clean == actual_clean:
        return "✅ 完全匹配"
    if expected_clean in actual_clean or actual_clean in expected_clean:
        return "⚠️ 部分匹配"
    return "❌ 不匹配"


def main() -> None:
    if not INPUT_FILE.exists():
        raise SystemExit("order_fuzzy.csv 不存在，请先生成。")

    with INPUT_FILE.open(encoding=ENCODING) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fieldnames = list(reader.fieldnames or []) + ["输出msg", "输出result", "接口状态", "匹配判断"]

    results = []
    for row in rows:
        command = row.get("模糊指令", "").strip()
        expected = row.get("预期功能", "").strip()
        api_result = call_api(command)
        row["输出msg"] = api_result["msg"]
        row["输出result"] = api_result["result"]
        row["接口状态"] = api_result["status"]
        row["匹配判断"] = judge(expected, api_result["result"])
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
