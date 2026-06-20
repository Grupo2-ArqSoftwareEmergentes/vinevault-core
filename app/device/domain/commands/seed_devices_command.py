from pydantic import BaseModel, Field


class SeedDevicesCommand(BaseModel):
    count: int = Field(..., gt=0)
    start_index: int = Field(default=1, ge=1)
