"""SSE 事件格式化工具。"""
from __future__ import annotations

import json
from typing import Any


def format_sse(event: str, data: Any) -> str:
    json_str = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {json_str}\n\n"


def sse_meta_event(response_data: dict) -> str:
    return format_sse("meta", response_data)


def sse_msg_delta_event(content: str) -> str:
    return format_sse("msg_delta", {"content": content})


def sse_done_event(response_data: dict) -> str:
    return format_sse("done", response_data)


def sse_error_event(message: str, code: int = 500) -> str:
    return format_sse("error", {"code": code, "message": message})
