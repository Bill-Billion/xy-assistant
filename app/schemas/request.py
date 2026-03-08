from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    query: str
    meta: dict[str, Any] | None = None
    user: Optional[str] = None
    # 前端可直接传入当前定位城市，天气优先级：query > meta.city > 该字段 > 默认
    city: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "sessionId": "27e4b59c1fda42a4b403b5b7df09a36e",
                "query": "帮我订个6点的闹钟",
                "city": "长沙",
                "meta": {"device": "speaker"},
                "user": "小张,小杨",
            }
        },
    }
