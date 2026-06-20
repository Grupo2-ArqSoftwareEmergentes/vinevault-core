from decimal import Decimal
from enum import Enum


class MetricThreshold(str, Enum):
    TEMPERATURE_MIN = "temperature_min"
    TEMPERATURE_MAX = "temperature_max"
    HUMIDITY_MIN = "humidity_min"
    HUMIDITY_MAX = "humidity_max"

    def label(self) -> str:
        labels = {
            "temperature_min": "Temperature min",
            "temperature_max": "Temperature max",
            "humidity_min": "Humidity min",
            "humidity_max": "Humidity max",
        }
        return labels.get(self.value, self.value)

    def unit(self) -> str:
        units = {
            "temperature_min": "°C",
            "temperature_max": "°C",
            "humidity_min": "%",
            "humidity_max": "%",
        }
        return units.get(self.value, "")

    def default_value(self) -> Decimal:
        defaults = {
            "temperature_min": Decimal("12"),
            "temperature_max": Decimal("16"),
            "humidity_min": Decimal("65"),
            "humidity_max": Decimal("80"),
        }
        return defaults[self.value]

