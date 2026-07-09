from enum import Enum


class AlertMetricType(str, Enum):
    PM25 = "PM25"
    CO2 = "CO2"
    TEMPERATURE = "TEMPERATURE"
    HUMIDITY = "HUMIDITY"
