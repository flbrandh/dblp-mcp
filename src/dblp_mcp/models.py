from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DBLP_RECORD_TYPES = {
    "article",
    "inproceedings",
    "proceedings",
    "book",
    "incollection",
    "phdthesis",
    "mastersthesis",
    "www",
    "data",
}

VENUE_FIELDS = ("journal", "booktitle", "series", "publisher", "school")
IDENTIFIER_FIELDS = ("doi", "isbn", "issn", "url", "ee")
SCALAR_FIELDS = (
    "title",
    "year",
    "pages",
    "volume",
    "number",
    "chapter",
    "crossref",
    "month",
    "address",
    "note",
)


@dataclass(slots=True)
class Contributor:
    name: str
    role: str
    position: int


@dataclass(slots=True)
class VenueLink:
    name: str
    venue_type: str
    position: int = 0


@dataclass(slots=True)
class Identifier:
    kind: str
    value: str


@dataclass(slots=True)
class PublicationRecord:
    dblp_key: str
    record_type: str
    title: str = ""
    year: int | None = None
    pages: str | None = None
    volume: str | None = None
    number: str | None = None
    chapter: str | None = None
    crossref: str | None = None
    month: str | None = None
    address: str | None = None
    note: str | None = None
    contributors: list[Contributor] = field(default_factory=list)
    venues: list[VenueLink] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)
    extra_fields: list[tuple[str, str, int]] = field(default_factory=list)
    source_mdate: str | None = None
    raw_attributes: dict[str, Any] = field(default_factory=dict)
