import json
import logging
import re
from datetime import date

from app.inventory_intelligence.domain.models.wine_autocomplete import WineAutocompleteResult, WineAutocompleteSuggestion
from app.inventory_intelligence.domain.services.wine_autocomplete_provider import WineAutocompleteProvider


logger = logging.getLogger(__name__)


class WineAutocompleteService:
    def __init__(self, provider: WineAutocompleteProvider):
        self.provider = provider

    async def suggest(self, wine_name: str, *, registration_date: date | None = None) -> WineAutocompleteResult:
        try:
            raw = await self.provider.generate(wine_name) if registration_date is None else await self.provider.generate(wine_name, registration_date=registration_date)
            if not isinstance(raw, str) or len(raw) > 65536:
                return WineAutocompleteResult()
            raw = raw.strip()
            # Tolerate a single Markdown fence, not arbitrary introductory prose.
            fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
            if fenced:
                raw = fenced.group(1)
            suggestion = WineAutocompleteResult.model_validate(json.loads(raw))
            # Fill all form keys; optional source metadata remains absent unless supplied.
            values = {field: getattr(suggestion, field) for field in WineAutocompleteSuggestion.model_fields}
            for field in ("sources", "search_suggestions_html", "registration_date", "estimated_fields", "estimation_basis"):
                if field in suggestion.model_fields_set:
                    values[field] = getattr(suggestion, field)
            return WineAutocompleteResult(**values)
        except Exception:
            # Do not log user names, prompts, provider payloads or credentials.
            logger.warning("Wine autocomplete unavailable or invalid; returning empty suggestions")
            return WineAutocompleteResult()
