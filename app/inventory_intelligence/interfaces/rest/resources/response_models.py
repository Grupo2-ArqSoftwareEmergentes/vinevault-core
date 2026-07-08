from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel

from app.inventory_intelligence.domain.models import AnalysisResult


class AnalysisResponse(BaseModel):
    id: UUID
    analysis_type: str
    content: str
    wine_cellar_id: UUID
    tokens_used: Optional[int]
    created_at: datetime

    @classmethod
    def from_domain(cls, result: AnalysisResult) -> "AnalysisResponse":
        return cls(
            id=result.id,
            analysis_type=result.analysis_type.value,
            content=result.content,
            wine_cellar_id=result.wine_cellar_id,
            tokens_used=result.tokens_used,
            created_at=result.created_at,
        )
