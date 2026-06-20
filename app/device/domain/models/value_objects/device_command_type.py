from enum import Enum


class DeviceCommandType(str, Enum):
    STANDBY = "STANDBY"
    WAKE = "WAKE"
    RESTART = "RESTART"