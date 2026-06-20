from enum import Enum


class DeviceStatus(str, Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    STANDBY = "STANDBY"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"