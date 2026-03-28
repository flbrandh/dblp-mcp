from __future__ import annotations

from .base import FulltextLookup, FulltextProvider
from .providers.acm import AcmPdfProvider
from .providers.arxiv import ArxivPdfProvider
from .providers.ieee import IeeePdfProvider
from .providers.openalex import OpenAlexPdfProvider

_PROVIDERS: tuple[FulltextProvider, ...] = (
    ArxivPdfProvider(),
    IeeePdfProvider(),
    AcmPdfProvider(),
    OpenAlexPdfProvider(),
)


def get_providers(lookup: FulltextLookup) -> list[FulltextProvider]:
    return [provider for provider in _PROVIDERS if provider.can_handle(lookup)]
