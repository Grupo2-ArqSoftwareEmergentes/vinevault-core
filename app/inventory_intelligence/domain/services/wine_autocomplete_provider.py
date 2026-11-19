from typing import Protocol
from datetime import date


class WineAutocompleteProvider(Protocol):
    async def generate(self, wine_name: str, *, registration_date: date | None = None) -> str: ...
