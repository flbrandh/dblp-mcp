"""OpenAlex abstract provider for DOI-backed publications."""

from __future__ import annotations

import json
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ...config import ABSTRACT_TIMEOUT_SECONDS, ensure_network_enabled
from ...text import normalize_for_search, normalize_text
from ..base import AbstractFetchResult, AbstractLookup

OPENALEX_WORKS_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
USER_AGENT = "dblp-mcp/0.1 (transparent abstract fetcher; contact repository owner)"


class OpenAlexProvider:
    name = "openalex"

    def can_handle(self, lookup: AbstractLookup) -> bool:
        return bool(lookup.doi)

    def build_attempted_url(self, lookup: AbstractLookup) -> str | None:
        if lookup.doi is None:
            return None
        return OPENALEX_WORKS_URL.format(doi=quote(lookup.doi, safe=""))

    def fetch(self, lookup: AbstractLookup) -> AbstractFetchResult | None:
        source_url = self.build_attempted_url(lookup)
        if source_url is None:
            return None

        ensure_network_enabled()
        request = Request(source_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=ABSTRACT_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            _validate_final_url(final_url, "api.openalex.org")
            payload = json.loads(response.read().decode("utf-8"))

        abstract_text = _materialize_abstract(payload.get("abstract_inverted_index"))
        if abstract_text is None:
            return None
        return AbstractFetchResult(
            abstract_text=abstract_text,
            abstract_norm=normalize_for_search(abstract_text),
            provider=self.name,
            source_url=source_url,
        )


def _materialize_abstract(abstract_inverted_index: object) -> str | None:
    if not isinstance(abstract_inverted_index, dict) or not abstract_inverted_index:
        return None

    positions: dict[int, str] = {}
    for token, offsets in abstract_inverted_index.items():
        if not isinstance(token, str) or not isinstance(offsets, list):
            continue
        for offset in offsets:
            if isinstance(offset, int):
                positions[offset] = token

    if not positions:
        return None

    ordered_tokens = [positions[index] for index in sorted(positions)]
    abstract_text = normalize_text(" ".join(ordered_tokens))
    return abstract_text or None


def _validate_final_url(final_url: str, expected_host: str) -> None:
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or parsed.netloc != expected_host:
        raise RuntimeError("provider redirected to an unexpected host")
