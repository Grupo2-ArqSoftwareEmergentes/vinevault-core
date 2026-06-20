from pydantic import BaseModel, Field


class UserId(BaseModel):
    user_id: int = Field(...)
