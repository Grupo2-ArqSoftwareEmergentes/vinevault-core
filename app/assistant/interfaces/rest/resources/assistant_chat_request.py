from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.domain.models import AssistantMode, HistoryMessage


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    space_id: UUID
    cellar_id: UUID | None = None
    mode: AssistantMode = AssistantMode.CHAT
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] | None = Field(default=None, max_length=10)
