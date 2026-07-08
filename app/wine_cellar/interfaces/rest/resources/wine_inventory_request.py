from pydantic import BaseModel, Field, field_validator


class CreateWineInventoryItemRequest(BaseModel):
    wine_name: str = Field(..., min_length=1)
    wine_type: str = Field(..., min_length=1)
    age_years: int = Field(..., ge=0)
    quantity: int = Field(..., ge=0)

    @field_validator("wine_name")
    @classmethod
    def normalize_wine_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Wine name must not be null or blank")
        return value.strip()

    @field_validator("wine_type")
    @classmethod
    def normalize_wine_type(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Wine type must not be null or blank")
        return value.strip()


class UpdateWineInventoryItemRequest(CreateWineInventoryItemRequest):
    pass
