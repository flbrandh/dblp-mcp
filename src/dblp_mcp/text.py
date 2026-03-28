from __future__ import annotations

import re
import unicodedata
from xml.etree.ElementTree import Element

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def normalize_for_search(value: str) -> str:
    return normalize_text(value).casefold()


def inner_text(element: Element) -> str:
    return normalize_text("".join(element.itertext()))
