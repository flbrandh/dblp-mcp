"""ACM Digital Library full-text provider for ACM DOI-backed publications."""

from __future__ import annotations

from urllib.parse import quote

from ..base import FulltextCandidate, FulltextLookup

ACM_PDF_URL = "https://dl.acm.org/doi/pdf/{doi}?download=true"
ACM_SOURCE_URL = "https://dl.acm.org/doi/{doi}"


class AcmPdfProvider:
    name = "acm_pdf"

    def can_handle(self, lookup: FulltextLookup) -> bool:
        return bool(lookup.doi and lookup.doi.casefold().startswith("10.1145/"))

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        if lookup.doi is None:
            return []
        doi = quote(lookup.doi, safe="/")
        source_url = ACM_SOURCE_URL.format(doi=doi)
        return [
            FulltextCandidate(
                provider=self.name,
                source_url=source_url,
                pdf_url=ACM_PDF_URL.format(doi=doi),
                request_headers={
                    "Accept": "application/pdf,*/*;q=0.8",
                    "Referer": source_url,
                },
            )
        ]
