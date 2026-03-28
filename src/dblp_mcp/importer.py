"""Streaming DBLP XML importer that builds the local SQLite search database."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from gzip import open as gzip_open
from html import unescape
from pathlib import Path
from re import compile as re_compile
from typing import BinaryIO, cast
from xml.etree.ElementTree import Element, XMLParser

from defusedxml.ElementTree import iterparse

from .database import connect, create_schema, rebuild_search_index
from .downloader import download_dblp_dump
from .models import (
    DBLP_RECORD_TYPES,
    IDENTIFIER_FIELDS,
    SCALAR_FIELDS,
    VENUE_FIELDS,
    Contributor,
    Identifier,
    PublicationRecord,
    VenueLink,
)
from .text import inner_text, normalize_for_search

DBLP_DTD_URL = "https://dblp.org/xml/dblp.dtd"
_ENTITY_RE = re_compile(r'<!ENTITY\s+(\w+)\s+"([^"]*)"\s*>')


def _open_xml_stream(xml_path: Path) -> BinaryIO:
    """Open plain or gzip-compressed DBLP XML streams in binary mode."""
    if xml_path.suffix == ".gz":
        return cast(BinaryIO, gzip_open(xml_path, "rb"))
    return xml_path.open("rb")


def _load_entity_map(xml_path: Path) -> dict[str, str]:
    """Load DBLP DTD entities so real-world DBLP XML can be parsed safely."""
    dtd_path = xml_path.with_name("dblp.dtd")
    if not dtd_path.exists():
        download_dblp_dump(destination=dtd_path, source_url=DBLP_DTD_URL, replace=False)

    entity_map: dict[str, str] = {}
    dtd_text = dtd_path.read_text(encoding="latin-1")
    for name, value in _ENTITY_RE.findall(dtd_text):
        entity_map[name] = unescape(value)
    return entity_map


def _build_xml_parser(xml_path: Path) -> XMLParser:
    """Construct an XML parser with DBLP entity declarations preloaded."""
    parser = XMLParser()
    parser.entity.update(_load_entity_map(xml_path))
    return parser


def _safe_int(value: str) -> int | None:
    """Parse an integer value and return ``None`` for malformed input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_record(element: Element) -> PublicationRecord:
    """Convert one DBLP record element into a normalized in-memory dataclass."""
    record = PublicationRecord(
        dblp_key=element.attrib["key"],
        record_type=element.tag,
        source_mdate=element.attrib.get("mdate"),
        raw_attributes=dict(element.attrib),
    )
    author_position = 0
    editor_position = 0
    venue_positions: dict[str, int] = {}
    field_positions: dict[str, int] = {}

    for child in element:
        text = inner_text(child)
        if not text:
            continue

        tag = child.tag
        if tag == "author":
            record.contributors.append(
                Contributor(name=text, role="author", position=author_position)
            )
            author_position += 1
            continue
        if tag == "editor":
            record.contributors.append(
                Contributor(name=text, role="editor", position=editor_position)
            )
            editor_position += 1
            continue
        if tag in VENUE_FIELDS:
            position = venue_positions.get(tag, 0)
            record.venues.append(
                VenueLink(name=text, venue_type=tag, position=position)
            )
            venue_positions[tag] = position + 1
            continue
        if tag in IDENTIFIER_FIELDS:
            record.identifiers.append(Identifier(kind=tag, value=text))
            continue
        if tag in SCALAR_FIELDS:
            if tag == "title":
                record.title = text
            elif tag == "year":
                record.year = _safe_int(text)
            else:
                setattr(record, tag, text)
            continue

        position = field_positions.get(tag, 0)
        record.extra_fields.append((tag, text, position))
        field_positions[tag] = position + 1

    return record


class ImportStats(dict[str, int]):
    """Small typed counter map tracking importer output sizes."""

    @classmethod
    def create(cls) -> ImportStats:
        return cls(
            publications=0,
            contributors=0,
            authorships=0,
            venues=0,
            venue_links=0,
            identifiers=0,
            extra_fields=0,
        )


class DblpImporter:
    def __init__(
        self, database_path: str | os.PathLike[str], batch_size: int = 500
    ) -> None:
        """Create a streaming importer targeting one SQLite file."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.database_path = Path(database_path)
        self.batch_size = batch_size

    def import_file(
        self,
        xml_path: str | os.PathLike[str],
        *,
        replace: bool = True,
    ) -> dict[str, object]:
        """Stream one DBLP XML/XML.GZ file into SQLite and rebuild the FTS index."""
        source_path = Path(xml_path)
        if not source_path.exists():
            raise FileNotFoundError(f"XML source not found: {source_path}")

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if not replace and self.database_path.exists():
            raise ValueError(
                "incremental append imports are not supported; use replace=True or a new database path"
            )
        temp_database = self.database_path.with_suffix(
            self.database_path.suffix + ".tmp"
        )
        if replace and temp_database.exists():
            temp_database.unlink()

        target_database = temp_database if replace else self.database_path
        connection = connect(target_database)
        create_schema(connection)

        import_run_id = self._start_import_run(connection, source_path)
        stats = ImportStats.create()
        contributor_cache: dict[tuple[str, str], int] = {}
        venue_cache: dict[tuple[str, str], int] = {}

        try:
            with _open_xml_stream(source_path) as stream:
                context = iterparse(
                    stream,
                    events=("start", "end"),
                    parser=_build_xml_parser(source_path),
                )
                root = None
                since_commit = 0
                for event, element in context:
                    if root is None and event == "start":
                        root = element
                    if event != "end" or element.tag not in DBLP_RECORD_TYPES:
                        continue

                    record = _build_record(element)
                    self._insert_record(
                        connection,
                        record,
                        contributor_cache,
                        venue_cache,
                        stats,
                    )
                    since_commit += 1
                    if since_commit >= self.batch_size:
                        connection.commit()
                        since_commit = 0
                    if root is not None:
                        root.clear()

            rebuild_search_index(connection)
            self._finish_import_run(
                connection, import_run_id, "completed", stats["publications"]
            )
            connection.commit()
        except Exception as exc:
            self._finish_import_run(
                connection, import_run_id, "failed", stats["publications"], str(exc)
            )
            connection.commit()
            connection.close()
            if replace and temp_database.exists():
                temp_database.unlink(missing_ok=True)
            raise

        connection.close()
        if replace:
            temp_database.replace(self.database_path)

        return {
            "database_path": str(self.database_path),
            "source_path": str(source_path),
            "replace": replace,
            "stats": dict(stats),
        }

    def _start_import_run(
        self, connection: sqlite3.Connection, source_path: Path
    ) -> int:
        """Create an ``import_runs`` row marking the start of an import."""
        cursor = connection.execute(
            """
            INSERT INTO import_runs(source_path, started_at, status, source_size_bytes)
            VALUES (?, ?, 'running', ?)
            """,
            (
                str(source_path),
                datetime.now(UTC).isoformat(),
                source_path.stat().st_size,
            ),
        )
        lastrowid = cursor.lastrowid
        if lastrowid is None:
            raise RuntimeError("failed to create import_runs row")
        return int(lastrowid)

    def _finish_import_run(
        self,
        connection: sqlite3.Connection,
        import_run_id: int,
        status: str,
        records_processed: int,
        error_message: str | None = None,
    ) -> None:
        """Update an ``import_runs`` row with completion status and optional error text."""
        connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?, status = ?, records_processed = ?, error_message = ?
            WHERE id = ?
            """,
            (
                datetime.now(UTC).isoformat(),
                status,
                records_processed,
                error_message,
                import_run_id,
            ),
        )

    def _insert_record(
        self,
        connection: sqlite3.Connection,
        record: PublicationRecord,
        contributor_cache: dict[tuple[str, str], int],
        venue_cache: dict[tuple[str, str], int],
        stats: ImportStats,
    ) -> None:
        """Persist one normalized publication plus related rows."""
        cursor = connection.execute(
            """
            INSERT INTO publications(
                dblp_key,
                record_type,
                title,
                title_norm,
                year,
                pages,
                volume,
                number,
                chapter,
                crossref,
                month,
                address,
                note,
                source_mdate
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.dblp_key,
                record.record_type,
                record.title,
                normalize_for_search(record.title),
                record.year,
                record.pages,
                record.volume,
                record.number,
                record.chapter,
                record.crossref,
                record.month,
                record.address,
                record.note,
                record.source_mdate,
            ),
        )
        lastrowid = cursor.lastrowid
        if lastrowid is None:
            raise RuntimeError("failed to insert publication row")
        publication_id = int(lastrowid)
        stats["publications"] += 1

        for contributor in record.contributors:
            contributor_id, inserted = self._get_or_create_contributor(
                connection, contributor_cache, contributor.name
            )
            connection.execute(
                """
                INSERT INTO publication_contributors(publication_id, contributor_id, role, position)
                VALUES (?, ?, ?, ?)
                """,
                (
                    publication_id,
                    contributor_id,
                    contributor.role,
                    contributor.position,
                ),
            )
            if inserted:
                stats["contributors"] += 1
            stats["authorships"] += 1

        for venue in record.venues:
            venue_id, inserted = self._get_or_create_venue(
                connection, venue_cache, venue.name, venue.venue_type
            )
            connection.execute(
                """
                INSERT INTO publication_venues(publication_id, venue_id, relation_type, position)
                VALUES (?, ?, ?, ?)
                """,
                (publication_id, venue_id, venue.venue_type, venue.position),
            )
            if inserted:
                stats["venues"] += 1
            stats["venue_links"] += 1

        for identifier in record.identifiers:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO publication_identifiers(publication_id, kind, value)
                VALUES (?, ?, ?)
                """,
                (publication_id, identifier.kind, identifier.value),
            )
            if cursor.rowcount > 0:
                stats["identifiers"] += 1

        for field_name, field_value, position in record.extra_fields:
            connection.execute(
                """
                INSERT INTO publication_fields(publication_id, field_name, field_value, position)
                VALUES (?, ?, ?, ?)
                """,
                (publication_id, field_name, field_value, position),
            )
            stats["extra_fields"] += 1

    def _get_or_create_contributor(
        self,
        connection: sqlite3.Connection,
        cache: dict[tuple[str, str], int],
        name: str,
    ) -> tuple[int, bool]:
        normalized = normalize_for_search(name)
        key = (normalized, name)
        cached_id = cache.get(key)
        if cached_id is not None:
            return cached_id, False

        cursor = connection.execute(
            """
            INSERT INTO contributors(name, name_norm)
            VALUES (?, ?)
            ON CONFLICT(name_norm, name) DO NOTHING
            RETURNING id
            """,
            (name, normalized),
        )
        row = cursor.fetchone()
        inserted = row is not None
        if row is None:
            row = connection.execute(
                "SELECT id FROM contributors WHERE name_norm = ? AND name = ?",
                (normalized, name),
            ).fetchone()
        contributor_id = int(row[0])
        cache[key] = contributor_id
        return contributor_id, inserted

    def _get_or_create_venue(
        self,
        connection: sqlite3.Connection,
        cache: dict[tuple[str, str], int],
        name: str,
        venue_type: str,
    ) -> tuple[int, bool]:
        normalized = normalize_for_search(name)
        key = (normalized, venue_type)
        cached_id = cache.get(key)
        if cached_id is not None:
            return cached_id, False

        cursor = connection.execute(
            """
            INSERT INTO venues(name, name_norm, venue_type)
            VALUES (?, ?, ?)
            ON CONFLICT(name_norm, venue_type) DO NOTHING
            RETURNING id
            """,
            (name, normalized, venue_type),
        )
        row = cursor.fetchone()
        inserted = row is not None
        if row is None:
            row = connection.execute(
                "SELECT id FROM venues WHERE name_norm = ? AND venue_type = ?",
                (normalized, venue_type),
            ).fetchone()
        venue_id = int(row[0])
        cache[key] = venue_id
        return venue_id, inserted
