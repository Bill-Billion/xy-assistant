from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse
from app.services.service_container import get_command_service
from app.services.command_service import CommandService

router = APIRouter(prefix="/api", tags=["command"])


@router.post("/command", response_model=CommandResponse)
async def handle_command(
    payload: CommandRequest,
    service: CommandService = Depends(get_command_service),
):
    if payload.stream:
        return StreamingResponse(
            service.handle_command_stream(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return await service.handle_command(payload)
