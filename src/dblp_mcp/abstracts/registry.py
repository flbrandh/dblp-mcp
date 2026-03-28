from __future__ import annotations

from .base import AbstractLookup, AbstractProvider
from .providers.arxiv import ArxivProvider
from .providers.openalex import OpenAlexProvider

_PROVIDERS: tuple[AbstractProvider, ...] = (
    ArxivProvider(),
    OpenAlexProvider(),
)


def get_providers(lookup: AbstractLookup) -> list[AbstractProvider]:
    return [provider for provider in _PROVIDERS if provider.can_handle(lookup)]
