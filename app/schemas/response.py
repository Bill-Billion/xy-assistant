from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class FunctionAnalysis(BaseModel):
    result: Optional[str] = None
    target: Optional[str] = None
    event: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    need_clarify: bool = False
    clarify_message: Optional[str] = None
    reasoning: Optional[str] = None
    advice: Optional[str] = None
    safety_notice: Optional[str] = None


class CommandResponse(BaseModel):
    code: int = 200
    msg: str
    session_id: str = Field(alias="sessionId")
    function_analysis: FunctionAnalysis

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "code": 200,
                "msg": "小雅：好的，我帮您设置今天下午6点的闹钟。",
                "sessionId": "27e4b59c1fda42a4b403b5b7df09a36e",
                "function_analysis": {
                    "result": "新增闹钟",
                    "target": "0d18h0m",
                    "event": None,
                    "status": None,
                    "confidence": 0.92,
                    "need_clarify": False,
                    "clarify_message": None,
                    "reasoning": "用户希望今天下午6点的提醒。",
                    "advice": None,
                    "safety_notice": None,
                },
            }
        },
    }
