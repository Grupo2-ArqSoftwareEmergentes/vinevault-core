from fastapi import APIRouter, Depends
from datetime import date, datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies import get_wine_autocomplete_service
from app.inventory_intelligence.applications.wine_autocomplete_service import WineAutocompleteService
from app.inventory_intelligence.domain.models.wine_autocomplete import WineAutocompleteResult


router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory AI"])


class WineAutocompleteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    wine_name: str = Field(min_length=1, max_length=255)
    registration_date: date | None = None

    @field_validator("registration_date")
    @classmethod
    def valid_registration_date(cls, value):
        if value is not None and not date(1900, 1, 1) <= value <= datetime.now(timezone.utc).date():
            raise ValueError("Registration date must be between 1900-01-01 and today (UTC)")
        return value


@router.post("/ai-autocomplete", response_model=WineAutocompleteResult, response_model_exclude_unset=True)
async def autocomplete_wine(
    payload: WineAutocompleteRequest,
    service: WineAutocompleteService = Depends(get_wine_autocomplete_service),
):
    return await service.suggest(payload.wine_name, registration_date=payload.registration_date)
