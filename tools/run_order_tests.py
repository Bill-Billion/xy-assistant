from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import json
from http.client import HTTPConnection
from urllib.parse import urlparse


ORDER_FILE = Path("order.csv")
OUTPUT_FILE = Path("order_with_results.csv")
API_URL = "http://0.0.0.0:8000/api/command"
ENCODING = "gbk"
TIMEOUT_SECONDS = 20.0
SEPARATOR = " || "


@dataclass
class CommandResult:
    command: str
    msg: str
    result: str
    match_comment: str


def split_examples(raw: str) -> List[str]:
    if not raw:
        return []
    text = raw.replace("\n", "")
    text = text.strip("【】")
    text = text.replace("“", "").replace("”", "")
    parts = [part.strip() for part in text.split("、")]
    return [p for p in parts if p]


def call_command_api(command: str, session_id: str | None = None) -> tuple[str, str]:
    payload = {"query": command}
    if session_id:
        payload["sessionId"] = session_id
    parsed = urlparse(API_URL)
    host = parsed.hostname or "0.0.0.0"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        conn = HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)
        conn.request(
            "POST",
            path,
            body=body_bytes,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        body = resp.read()
        if resp.status >= 400:
            return f"(HTTP {resp.status}: {body.decode('utf-8', errors='ignore')})", ""
        data = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"(接口调用失败：{exc})", ""
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    msg = str(data.get("msg") or "")
    function_analysis = data.get("function_analysis") or {}
    result = str(function_analysis.get("result") or "")
    return msg, result


def tokenize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\u4e00-\u9fa5]+", "", text)
    return text


def evaluate_match(expected: str, actual_msg: str, actual_result: str) -> str:
    expected_clean = tokenize(expected)
    if not expected_clean:
        expected_clean = ""

    result_clean = tokenize(actual_result)
    msg_clean = tokenize(actual_msg)

    function_ratio = difflib.SequenceMatcher(None, expected_clean, result_clean).ratio() if result_clean else 0.0
    content_ratio = difflib.SequenceMatcher(None, expected_clean, msg_clean).ratio() if msg_clean else 0.0
    score = 0.6 * function_ratio + 0.4 * content_ratio

    if score >= 0.75:
        verdict = "匹配"
    elif score >= 0.5:
        verdict = "部分匹配"
    else:
        verdict = "不匹配"

    return f"{verdict}(score={score:.2f},功能={function_ratio:.2f},内容={content_ratio:.2f})"


def process_row(row: dict[str, str]) -> List[CommandResult]:
    examples = split_examples(row.get("示例语句", ""))
    if not examples:
        return []

    expected = row.get("预期操作/响应", "")
    session_id = None
    command_results: List[CommandResult] = []
    for command in examples:
        msg, result = call_command_api(command, session_id=session_id)
        match_comment = evaluate_match(expected, msg, result)
        command_results.append(CommandResult(command, msg, result, match_comment))
    return command_results


def main() -> None:
    if not ORDER_FILE.exists():
        raise FileNotFoundError(f"未找到 {ORDER_FILE}")

    with ORDER_FILE.open(encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if "输出msg" not in fieldnames:
        fieldnames += ["输出msg"]
    if "输出result" not in fieldnames:
        fieldnames += ["输出result"]
    if "和预期操作匹配程度" not in fieldnames:
        fieldnames += ["和预期操作匹配程度"]

    updated_rows: List[dict[str, str]] = []
    for row in rows:
        results = process_row(row)
        if results:
            row["输出msg"] = SEPARATOR.join(r.msg for r in results)
            row["输出result"] = SEPARATOR.join(r.result for r in results)
            row["和预期操作匹配程度"] = SEPARATOR.join(r.match_comment for r in results)
        else:
            row.setdefault("输出msg", "")
            row.setdefault("输出result", "")
            row.setdefault("和预期操作匹配程度", "")
        updated_rows.append(row)

    with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    summary = {
        "total_rows": len(rows),
        "processed_rows": sum(1 for r in updated_rows if r.get("输出msg")),
        "output_file": str(OUTPUT_FILE),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
