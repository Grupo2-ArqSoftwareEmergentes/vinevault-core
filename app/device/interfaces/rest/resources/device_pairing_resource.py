from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DevicePairingResource(BaseModel):
    device_id: UUID
    claim_token: Optional[str] = None
