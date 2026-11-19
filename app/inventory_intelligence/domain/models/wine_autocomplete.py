from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


Text = Annotated[str, Field(max_length=255)]
Year = Annotated[int, Field(strict=True, ge=1000, le=9999)]


class WineAutocompleteSuggestion(BaseModel):
    """Closed output allowlist, deliberately independent of WineItemDetails/cata."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, allow_inf_nan=False)

    winery: Text | None = None
    vintage: Annotated[str, Field(pattern=r"^(NV|[0-9]{4})$")] | None = None
    country: Annotated[str, Field(max_length=100)] | None = None
    region: Text | None = None
    denomination: Text | None = None
    grape_type: Text | None = None
    format: Annotated[str, Field(max_length=50)] | None = None
    aging: Text | None = None
    alcohol: Annotated[str, Field(max_length=20)] | Annotated[float, Field(strict=True, ge=0, le=100)] | None = None
    drinking_window_start: Year | None = None
    drinking_window_end: Year | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_strings(cls, value):
        if isinstance(value, dict):
            return {key: None if isinstance(item, str) and not item.strip() else item for key, item in value.items()}
        return value

    @model_validator(mode="after")
    def chronological_window(self):
        if self.drinking_window_start is not None and self.drinking_window_end is not None:
            if self.drinking_window_start > self.drinking_window_end:
                raise ValueError("Invalid drinking window")
        return self


class WineAutocompleteGeneration(WineAutocompleteSuggestion):
    estimated_fields: list[Literal["drinking_window_start", "drinking_window_end"]] = Field(default_factory=list, max_length=2)
    estimation_basis: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def estimates_are_explicit(self):
        if len(set(self.estimated_fields)) != len(self.estimated_fields):
            raise ValueError("Duplicate estimated fields")
        if self.estimated_fields:
            if not self.estimation_basis or not self.estimation_basis.strip():
                raise ValueError("Estimates require an explanation")
            for field in self.estimated_fields:
                if getattr(self, field) is None:
                    raise ValueError("Estimated fields require a value")
        return self


class WineAutocompleteSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(max_length=300)
    url: HttpUrl


class WineAutocompleteResult(WineAutocompleteGeneration):
    # Response metadata, never inventory fields or part of the generation schema.
    sources: list[WineAutocompleteSource] | None = Field(default=None, max_length=10)
    search_suggestions_html: str | None = Field(default=None, max_length=50000)
    registration_date: date | None = None
