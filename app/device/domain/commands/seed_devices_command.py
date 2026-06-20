from pydantic import BaseModel, Field


class SeedDevicesCommand(BaseModel):
    count: int = Field(..., gt=0)
