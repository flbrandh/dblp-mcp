from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AbstractLookup:
    doi: str | None = None
    arxiv_id: str | None = None


@dataclass(slots=True)
class AbstractFetchResult:
    abstract_text: str
    abstract_norm: str
    provider: str
    source_url: str


class AbstractProvider(Protocol):
    name: str

    def can_handle(self, lookup: AbstractLookup) -> bool:
        ...

    def build_attempted_url(self, lookup: AbstractLookup) -> str | None:
        ...

    def fetch(self, lookup: AbstractLookup) -> AbstractFetchResult | None:
        ...
