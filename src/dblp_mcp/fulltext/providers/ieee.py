"""IEEE Xplore full-text provider for IEEE DOI-backed publications."""

from __future__ import annotations

from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ...config import (
    FULLTEXT_TIMEOUT_SECONDS,
    ensure_fulltext_network_enabled,
    provider_request_delay,
)
from ..base import FulltextCandidate, FulltextLookup

DOI_RESOLVER_URL = "https://doi.org/{doi}"
IEEE_DOCUMENT_HOST = "ieeexplore.ieee.org"
IEEE_PDF_URL = "https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0"


class IeeePdfProvider:
    name = "ieee_pdf"

    def can_handle(self, lookup: FulltextLookup) -> bool:
        return bool(lookup.doi and lookup.doi.casefold().startswith("10.1109/"))

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        if lookup.doi is None:
            return []
        resolver_url = DOI_RESOLVER_URL.format(doi=quote(lookup.doi, safe=""))
        ensure_fulltext_network_enabled()
        provider_request_delay(self.name)
        request = Request(resolver_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=FULLTEXT_TIMEOUT_SECONDS) as response:
            final_url = (
                response.geturl() if hasattr(response, "geturl") else resolver_url
            )
            arnumber = _extract_arnumber(final_url)
            if arnumber is None:
                return []
            pdf_url = IEEE_PDF_URL.format(arnumber=arnumber)
            return [
                FulltextCandidate(
                    provider=self.name,
                    source_url=final_url,
                    pdf_url=pdf_url,
                    request_headers={
                        "Accept": "application/pdf,*/*;q=0.8",
                        "Referer": "https://ieeexplore.ieee.org/",
                    },
                )
            ]


def _extract_arnumber(final_url: str) -> str | None:
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or parsed.netloc != IEEE_DOCUMENT_HOST:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "document" and parts[1].isdigit():
        return parts[1]
    return None
