from enum import Enum


class MetricThreshold(str, Enum):    
    CO2 = "CO2"
    TEMPERATURE = "TEMPERATURE"
    HUMIDITY = "HUMIDITY"

    def label(self) -> str:
        labels = {            
            "CO2": "CO2",
            "TEMPERATURE": "Temperature",
            "HUMIDITY": "Humidity"
        }
        return labels.get(self.value, self.value)

    def unit(self) -> str:
        units = {            
            "CO2": "ppm",
            "TEMPERATURE": "°C",
            "HUMIDITY": "%"
        }
        return units.get(self.value, "")