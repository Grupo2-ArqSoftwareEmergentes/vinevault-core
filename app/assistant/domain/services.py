from typing import Protocol

from .models import AssistantMode, CellarSummary, InventoryContext, SpaceSummary


class InventoryContextReader(Protocol):
    async def read(self, space: SpaceSummary, cellar: CellarSummary | None) -> InventoryContext: ...


class AssistantProvider(Protocol):
    async def reply(self, messages: list[dict[str, str]], mode: AssistantMode) -> str: ...
