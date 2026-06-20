from enum import Enum


class DeviceCommandStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"