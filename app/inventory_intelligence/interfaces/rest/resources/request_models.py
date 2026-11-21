from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class BaseAiRequest(BaseModel):
    wine_cellar_id: UUID


class AnalyzeStockRequest(BaseAiRequest):
    pass


class RecommendPurchasesRequest(BaseAiRequest):
    pass


class MonthlyReportRequest(BaseAiRequest):
    pass


class ChatRequest(BaseAiRequest):
    user_query: str = Field(..., min_length=1, max_length=1000)

    @field_validator("user_query")
    @classmethod
    def not_blank_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("User query must not be null or blank")
        return value.strip()
