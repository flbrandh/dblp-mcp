from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class FulltextLookup:
    doi: str | None = None
    arxiv_id: str | None = None


@dataclass(slots=True)
class FulltextCandidate:
    provider: str
    source_url: str
    pdf_url: str
    request_headers: dict[str, str] | None = None


class FulltextProvider(Protocol):
    name: str

    def can_handle(self, lookup: FulltextLookup) -> bool:
        ...

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        ...
