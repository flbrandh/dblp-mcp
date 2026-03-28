"""arXiv full-text provider for arXiv-backed publications."""

from __future__ import annotations

from urllib.parse import quote

from ..base import FulltextCandidate, FulltextLookup

ARXIV_PDF_URL = "https://export.arxiv.org/pdf/{arxiv_id}.pdf"


class ArxivPdfProvider:
    name = "arxiv_pdf"

    def can_handle(self, lookup: FulltextLookup) -> bool:
        return bool(lookup.arxiv_id)

    def fetch_candidates(self, lookup: FulltextLookup) -> list[FulltextCandidate]:
        if lookup.arxiv_id is None:
            return []
        pdf_url = ARXIV_PDF_URL.format(arxiv_id=quote(lookup.arxiv_id, safe=""))
        return [
            FulltextCandidate(
                provider=self.name,
                source_url=pdf_url,
                pdf_url=pdf_url,
            )
        ]
