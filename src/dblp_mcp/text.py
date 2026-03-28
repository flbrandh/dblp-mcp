"""Text normalization helpers used during import and search."""

from __future__ import annotations

import re
import unicodedata
from xml.etree.ElementTree import Element

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize Unicode and collapse whitespace to a single-space form."""
    text = unicodedata.normalize("NFKC", value or "")
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def normalize_for_search(value: str) -> str:
    """Normalize text and case-fold it for case-insensitive lookup fields."""
    return normalize_text(value).casefold()


def inner_text(element: Element) -> str:
    """Join all descendant text nodes from an XML element and normalize them."""
    return normalize_text("".join(element.itertext()))
