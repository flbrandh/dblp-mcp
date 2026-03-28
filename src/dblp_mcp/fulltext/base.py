"""Shared dataclasses and protocol contracts for full-text providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class FulltextLookup:
    """Lookup identifiers that full-text providers may know how to use."""

    doi: str | None = None
    arxiv_id: str | None = None


@dataclass(slots=True)
class FulltextCandidate:
    """One provider-supplied candidate PDF URL plus request metadata."""

    provider: str
    source_url: str
    pdf_url: str
    request_headers: dict[str, str] | None = None


class FulltextProvider(Protocol):
    """Protocol implemented by every source-specific full-text provider."""

    name: str

    def can_handle(self, lookup: FulltextLookup) -> bool:
        ...

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        ...
