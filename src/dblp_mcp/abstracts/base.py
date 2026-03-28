"""Shared dataclasses and protocol contracts for abstract providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AbstractLookup:
    """Lookup identifiers that abstract providers may know how to use."""

    doi: str | None = None
    arxiv_id: str | None = None


@dataclass(slots=True)
class AbstractFetchResult:
    """Normalized provider result ready for caching in SQLite."""

    abstract_text: str
    abstract_norm: str
    provider: str
    source_url: str


class AbstractProvider(Protocol):
    """Protocol implemented by every source-specific abstract provider."""

    name: str

    def can_handle(self, lookup: AbstractLookup) -> bool: ...

    def build_attempted_url(self, lookup: AbstractLookup) -> str | None: ...

    def fetch(self, lookup: AbstractLookup) -> AbstractFetchResult | None: ...
