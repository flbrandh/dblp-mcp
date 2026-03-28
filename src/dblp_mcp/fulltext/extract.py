from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from ..text import normalize_for_search, normalize_text


@dataclass(slots=True)
class PdfArtifacts:
    full_text: str
    full_text_norm: str
    page_count: int
    image_status: str
    page_image_paths: list[str]


def extract_pdf_artifacts(pdf_path: str | Path) -> PdfArtifacts:
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("pdf has no pages")

    _validate_not_presentation(reader)

    chunks: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        normalized = normalize_text(text)
        if normalized:
            chunks.append(normalized)

    full_text = normalize_text("\n\n".join(chunks))
    if len(full_text) < 50:
        raise ValueError("pdf text extraction produced too little text")

    return PdfArtifacts(
        full_text=full_text,
        full_text_norm=normalize_for_search(full_text),
        page_count=page_count,
        image_status="unsupported",
        page_image_paths=[],
    )


def _validate_not_presentation(reader: PdfReader) -> None:
    landscape_pages = 0
    for page in reader.pages:
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        if height <= 0:
            continue
        if width / height > 1.1:
            landscape_pages += 1
    if landscape_pages and landscape_pages >= max(1, len(reader.pages) // 2):
        raise ValueError("pdf appears presentation-like rather than paper-like")
