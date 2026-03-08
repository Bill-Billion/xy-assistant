from fastapi import APIRouter, Depends

from app.schemas.request import CommandRequest
from app.schemas.response import CommandResponse
from app.services.service_container import get_command_service
from app.services.command_service import CommandService

router = APIRouter(prefix="/api", tags=["command"])


@router.post("/command", response_model=CommandResponse)
async def handle_command(
    payload: CommandRequest,
    service: CommandService = Depends(get_command_service),
) -> CommandResponse:
    return await service.handle_command(payload)
