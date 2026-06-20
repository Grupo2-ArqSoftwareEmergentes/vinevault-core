from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class ClaimDeviceCommand(BaseModel):
    claim_token: str = Field(..., min_length=1)
    space_id: UUID
    user_id: int

    @field_validator('claim_token')
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Claim token must not be null or blank")
        return v
