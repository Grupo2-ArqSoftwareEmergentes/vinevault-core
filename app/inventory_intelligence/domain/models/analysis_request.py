from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from .analysis_type import AnalysisType


class AnalysisRequest(BaseModel):
    analysis_type: AnalysisType
    wine_cellar_id: UUID
    user_query: Optional[str] = Field(default=None, max_length=1000)
    user_id: int
