"""OpenAlex full-text provider for DOI-backed publications with OA PDFs."""

from __future__ import annotations

import json
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ...config import FULLTEXT_TIMEOUT_SECONDS, ensure_network_enabled
from ..base import FulltextCandidate, FulltextLookup

OPENALEX_WORKS_URL = "https://api.openalex.org/works/https://doi.org/{doi}"
USER_AGENT = "dblp-mcp/0.1 (transparent lawful fulltext fetcher; contact repository owner)"
_DISALLOWED_HOST_FRAGMENTS = ("author",)


class OpenAlexPdfProvider:
    name = "openalex_pdf"

    def can_handle(self, lookup: FulltextLookup) -> bool:
        return bool(lookup.doi)

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        if lookup.doi is None:
            return []
        source_url = OPENALEX_WORKS_URL.format(doi=quote(lookup.doi, safe=""))
        ensure_network_enabled()
        request = Request(source_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=FULLTEXT_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            _validate_final_url(final_url)
            payload = json.loads(response.read().decode("utf-8"))

        candidates: list[FulltextCandidate] = []
        for location in payload.get("locations") or []:
            if not isinstance(location, dict):
                continue
            pdf_url = location.get("pdf_url")
            if not isinstance(pdf_url, str) or not pdf_url:
                continue
            if not _is_allowed_pdf_url(pdf_url):
                continue
            source = location.get("landing_page_url") or source_url
            candidates.append(
                FulltextCandidate(
                    provider=self.name,
                    source_url=str(source),
                    pdf_url=pdf_url,
                )
            )
        return candidates


def _validate_final_url(final_url: str) -> None:
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or parsed.netloc != "api.openalex.org":
        raise RuntimeError("provider redirected to an unexpected host")


def _is_allowed_pdf_url(pdf_url: str) -> bool:
    parsed = urlparse(pdf_url)
    if parsed.scheme != "https":
        return False
    netloc = parsed.netloc.casefold()
    if any(fragment in netloc for fragment in _DISALLOWED_HOST_FRAGMENTS):
        return False
    return True
