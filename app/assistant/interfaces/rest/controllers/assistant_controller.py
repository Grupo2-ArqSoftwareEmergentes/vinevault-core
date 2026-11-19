from fastapi import APIRouter, Depends, HTTPException

from app.assistant.applications.chat_service import AssistantChatService
from app.assistant.domain.models import AssistantUnavailableError, CellarSummary, SpaceSummary
from app.dependencies import get_assistant_chat_service
from ..resources import AssistantChatRequest, AssistantChatResponse
from ..security import authorize_assistant_request


router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    payload: AssistantChatRequest,
    authorized: tuple[SpaceSummary, CellarSummary | None] = Depends(authorize_assistant_request),
    service: AssistantChatService = Depends(get_assistant_chat_service),
):
    space, cellar = authorized
    try:
        reply, summary = await service.chat(
            space=space, cellar=cellar, mode=payload.mode, message=payload.message, history=payload.history or [],
        )
    except AssistantUnavailableError as exc:
        headers = {"Retry-After": "30"} if exc.status_code == 429 else None
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}, headers=headers) from exc
    return AssistantChatResponse(reply=reply, mode=payload.mode, context_summary=summary)
