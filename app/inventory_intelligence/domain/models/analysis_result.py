from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .analysis_type import AnalysisType


class AnalysisResult(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_type: AnalysisType
    content: str = Field(..., min_length=1)
    wine_cellar_id: UUID
    tokens_used: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
