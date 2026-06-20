from pydantic import BaseModel
from uuid import UUID


class ResetDeviceAssignmentCommand(BaseModel):
    device_id: UUID
    user_id: int
