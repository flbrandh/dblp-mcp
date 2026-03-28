"""arXiv abstract provider for arXiv-backed publications."""

from __future__ import annotations

from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from xml.etree.ElementTree import fromstring

from ...config import ABSTRACT_TIMEOUT_SECONDS, ensure_network_enabled
from ...text import normalize_for_search, normalize_text
from ..base import AbstractFetchResult, AbstractLookup

ARXIV_API_URL = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
USER_AGENT = "dblp-mcp/0.1 (transparent abstract fetcher; contact repository owner)"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivProvider:
    name = "arxiv"

    def can_handle(self, lookup: AbstractLookup) -> bool:
        return bool(lookup.arxiv_id)

    def build_attempted_url(self, lookup: AbstractLookup) -> str | None:
        if lookup.arxiv_id is None:
            return None
        return ARXIV_API_URL.format(arxiv_id=quote(lookup.arxiv_id, safe=""))

    def fetch(self, lookup: AbstractLookup) -> AbstractFetchResult | None:
        source_url = self.build_attempted_url(lookup)
        if source_url is None:
            return None

        ensure_network_enabled()
        request = Request(source_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=ABSTRACT_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            _validate_final_url(final_url, "export.arxiv.org")
            payload = response.read()

        root = fromstring(payload)
        entry = root.find("atom:entry", ATOM_NAMESPACE)
        if entry is None:
            return None

        summary = entry.findtext("atom:summary", default="", namespaces=ATOM_NAMESPACE)
        abstract_text = normalize_text(summary)
        if not abstract_text:
            return None
        return AbstractFetchResult(
            abstract_text=abstract_text,
            abstract_norm=normalize_for_search(abstract_text),
            provider=self.name,
            source_url=source_url,
        )


def _validate_final_url(final_url: str, expected_host: str) -> None:
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or parsed.netloc != expected_host:
        raise RuntimeError("provider redirected to an unexpected host")
