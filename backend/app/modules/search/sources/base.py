"""Abstract SourceAdapter — every data source implements this.

Adding a new source = create a new file in this package that subclasses
SourceAdapter, register it in `sources/__init__.py` (or the registry below),
and add the relevant slot keys to `core/slot_schema.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


Confidence = Literal["high", "medium", "low"]


class FetchResult(BaseModel):
    """One value retrieved from a source for one slot."""

    slot_key: str
    value: float | None = Field(
        default=None,
        description="None means 'not yet released / market closed' — do NOT default to 0.",
    )
    unit: str
    raw_text: str = ""
    source_url: str = ""
    confidence: Confidence = "high"
    fetched_at: str | None = None  # ISO timestamp set by store on insert


class SourceAdapter(ABC):
    """Pull-style adapter. Subclasses fetch market data for a given date."""

    name: str
    """Stable adapter identifier referenced by SlotDef.source."""

    provides: list[str]
    """SlotDef.key values this adapter is responsible for."""

    @abstractmethod
    async def fetch(self, target_date: date) -> list[FetchResult]:
        """Return one FetchResult per slot in `provides`.

        Must return one entry per provided slot even on failure
        (set value=None, confidence='low', raw_text with error reason).
        """
        ...


# ── Registry ────────────────────────────────────────────────
# Adapters self-register on import. Keep this dict small;
# orchestrator looks up by name.

_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Decorator to add adapter to global registry."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must set class attribute `name`")
    _REGISTRY[cls.name] = cls
    return cls


def get_adapter(name: str) -> type[SourceAdapter]:
    if name not in _REGISTRY:
        raise KeyError(f"No source adapter registered with name '{name}'")
    return _REGISTRY[name]


def list_adapters() -> list[str]:
    return sorted(_REGISTRY)
