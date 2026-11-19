from pydantic import BaseModel

from app.assistant.domain.models import AssistantMode, ContextSummary


class AssistantChatResponse(BaseModel):
    reply: str
    mode: AssistantMode
    context_summary: ContextSummary
