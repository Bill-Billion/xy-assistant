from __future__ import annotations

from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class FunctionAnalysis(BaseModel):
    result: Optional[str] = None
    target: Optional[str] = None
    event: Optional[str] = None
    status: Optional[str] = None
    parsed_time: Optional[str] = None
    time_text: Optional[str] = None
    time_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    time_source: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    need_clarify: bool = False
    clarify_message: Optional[str] = None
    reasoning: Optional[str] = None
    advice: Optional[str] = None
    safety_notice: Optional[str] = None
    weather_condition: Optional[str] = None
    weather_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    weather_summary: Optional[str] = None
    weather_detail: Optional[Dict[str, Any]] = None
    weather_evidence: Optional[List[str]] = None
    weather_judgement: Optional[str] = None
    weather_needs_realtime: Optional[bool] = None


class CommandResponse(BaseModel):
    code: int = 200
    msg: str
    session_id: str = Field(alias="sessionId")
    requires_selection: bool = Field(default=False, alias="requiresSelection")
    function_analysis: FunctionAnalysis

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "code": 200,
                "msg": "小雅：好的，我帮您设置今天下午6点的闹钟。",
                "sessionId": "27e4b59c1fda42a4b403b5b7df09a36e",
                "requiresSelection": False,
                "function_analysis": {
                    "result": "新增闹钟",
                    "target": "2024-09-20 18:00:00",
                    "parsed_time": "2024-09-20 18:00:00",
                    "time_text": "今天下午6点",
                    "time_confidence": 0.92,
                    "time_source": "llm",
                    "event": None,
                    "status": None,
                    "confidence": 0.92,
                    "need_clarify": False,
                    "clarify_message": None,
                    "reasoning": "用户希望今天下午6点的提醒。",
                    "advice": None,
                    "safety_notice": None,
                    "weather_condition": None,
                    "weather_confidence": None,
                    "weather_summary": None,
                    "weather_detail": None,
                    "weather_evidence": None,
                    "weather_judgement": None,
                    "weather_needs_realtime": None,
                },
            }
        },
    }
