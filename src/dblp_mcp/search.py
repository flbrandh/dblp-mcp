"""Query helpers for the imported DBLP SQLite database.

This module contains read-side operations only: full-text search, detailed
publication lookup, and database status reporting.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .config import (
    data_dir_was_explicitly_configured,
    display_path,
    relative_to_data_dir,
)
from .database import connect, ensure_abstract_schema, ensure_fulltext_schema
from .text import normalize_for_search

_YEAR_TOKEN_RE = re.compile(r"^(19|20)\d{2}$")


def _normalize_term_groups(
    term_groups: list[list[str]],
) -> tuple[list[list[str]], list[list[int]]]:
    """Normalize structured term groups and extract year-like OR-groups."""
    normalized_groups: list[list[str]] = []
    year_groups: list[list[int]] = []
    for group in term_groups:
        cleaned_group: list[str] = []
        cleaned_years: list[int] = []
        for term in group:
            cleaned = term.strip().strip(",.:;()[]{}")
            if not cleaned:
                continue
            if _YEAR_TOKEN_RE.match(cleaned):
                cleaned_years.append(int(cleaned))
            else:
                cleaned_group.append(cleaned.replace(chr(34), ""))
        if cleaned_group:
            normalized_groups.append(cleaned_group)
        elif cleaned_years:
            year_groups.append(cleaned_years)
    return normalized_groups, year_groups


def _build_fts_query(term_groups: list[list[str]]) -> str | None:
    """Build an FTS query where inner groups mean OR and groups mean AND."""
    if not term_groups:
        return None
    parts = []
    for group in term_groups:
        if len(group) == 1:
            parts.append(f'"{group[0]}"')
        else:
            parts.append("(" + " OR ".join(f'"{term}"' for term in group) + ")")
    return " AND ".join(parts)


def _record_type_rank(record_type: str) -> int:
    """Rank paper-like records ahead of proceedings/container records."""
    if record_type in {
        "article",
        "inproceedings",
        "incollection",
        "phdthesis",
        "mastersthesis",
    }:
        return 0
    if record_type in {"informal", "data"}:
        return 1
    if record_type in {"proceedings", "book", "reference", "collection"}:
        return 2
    return 1


def search_publications(
    database_path: str | Path,
    term_groups: list[list[str]],
    *,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    record_types: list[str] | None = None,
    contributor: str | None = None,
    venue: str | None = None,
    include_contributors: bool = False,
    include_venues: bool = False,
) -> dict[str, object]:
    """Search publications with structured OR-groups combined by AND.

    Each inner list in ``term_groups`` is treated as an OR-group. The outer list
    is treated as AND across groups. Year-like terms are extracted into year
    filters automatically. By default, list results are kept compact;
    contributors and venues can be added explicitly.
    """
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")

    normalized_groups, year_groups = _normalize_term_groups(term_groups)
    if not normalized_groups and not year_groups:
        raise ValueError("term_groups must contain at least one non-empty term")
    effective_year_from = year_from
    effective_year_to = year_to

    fts_query = _build_fts_query(normalized_groups)

    connection = connect(database_path)
    conditions: list[str] = []
    parameters: list[object] = []
    if fts_query is not None:
        conditions.append("publication_search MATCH ?")
        parameters.append(fts_query)

    if effective_year_from is not None:
        conditions.append("publications.year >= ?")
        parameters.append(effective_year_from)
    if effective_year_to is not None:
        conditions.append("publications.year <= ?")
        parameters.append(effective_year_to)
    for year_group in year_groups:
        placeholders = ", ".join("?" for _ in year_group)
        conditions.append(f"publications.year IN ({placeholders})")
        parameters.extend(year_group)
    if record_types:
        placeholders = ", ".join("?" for _ in record_types)
        conditions.append(f"publications.record_type IN ({placeholders})")
        parameters.extend(record_types)
    if contributor:
        conditions.append(
            "EXISTS (SELECT 1 FROM publication_contributors pc JOIN contributors c ON c.id = pc.contributor_id WHERE pc.publication_id = publications.id AND c.name_norm LIKE ?)"
        )
        parameters.append(f"%{normalize_for_search(contributor)}%")
    if venue:
        conditions.append(
            "EXISTS (SELECT 1 FROM publication_venues pv JOIN venues v ON v.id = pv.venue_id WHERE pv.publication_id = publications.id AND v.name_norm LIKE ?)"
        )
        parameters.append(f"%{normalize_for_search(venue)}%")

    where_clause = " AND ".join(conditions) if conditions else "1 = 1"
    sql = f"""
        SELECT
            publications.id,
            publications.dblp_key,
            publications.record_type,
            publications.title,
            publications.year,
            bm25(publication_search) AS score,
            CASE
                WHEN publications.record_type IN ('article', 'inproceedings', 'incollection', 'phdthesis', 'mastersthesis') THEN 0
                WHEN publications.record_type IN ('proceedings', 'book', 'reference', 'collection') THEN 2
                ELSE 1
            END AS type_rank
        FROM publication_search
        JOIN publications ON publications.id = publication_search.rowid
        WHERE {where_clause}
        ORDER BY type_rank, score, publications.year DESC, publications.title ASC
        LIMIT ?
    """
    parameters.append(limit)
    rows = connection.execute(sql, parameters).fetchall()
    results = []
    for row in rows:
        item: dict[str, object] = {
            "dblp_key": row["dblp_key"],
            "record_type": row["record_type"],
            "title": row["title"],
            "year": row["year"],
            "score": row["score"],
        }
        if include_contributors:
            item["contributors"] = _contributors_for_publication(connection, row["id"])
        if include_venues:
            item["venues"] = _venues_for_publication(connection, row["id"])
        results.append(item)
    connection.close()
    return {"term_groups": normalized_groups, "count": len(results), "results": results}


def get_publication(
    database_path: str | Path,
    dblp_key: str,
    *,
    include_identifiers: bool = False,
    include_extra_fields: bool = False,
    include_fulltext: bool = False,
) -> dict[str, object] | None:
    """Load one publication and its related normalized records.

    The returned payload includes core bibliographic fields, contributors, venues,
    and full abstract text when available. Identifiers, extra fields, and
    fulltext metadata are omitted by default to keep MCP responses compact.
    """
    connection = connect(database_path)
    ensure_abstract_schema(connection)
    ensure_fulltext_schema(connection)
    connection.commit()
    row = connection.execute(
        """
        SELECT id, dblp_key, record_type, title, year, pages, volume, number, chapter, crossref,
               month, address, note, source_mdate
        FROM publications
        WHERE dblp_key = ?
        """,
        (dblp_key,),
    ).fetchone()
    if row is None:
        connection.close()
        return None

    publication: dict[str, object] = {
        "dblp_key": row["dblp_key"],
        "record_type": row["record_type"],
        "title": row["title"],
        "year": row["year"],
        "pages": row["pages"],
        "volume": row["volume"],
        "number": row["number"],
        "chapter": row["chapter"],
        "crossref": row["crossref"],
        "month": row["month"],
        "address": row["address"],
        "note": row["note"],
        "source_mdate": row["source_mdate"],
        "contributors": _contributors_for_publication(connection, row["id"]),
        "venues": _venues_for_publication(connection, row["id"]),
        "abstract": _abstract_for_publication(connection, row["id"]),
    }
    if include_fulltext:
        publication["fulltext"] = _fulltext_for_publication(connection, row["id"])
    if include_identifiers:
        publication["identifiers"] = [
            dict(identifier)
            for identifier in connection.execute(
                "SELECT kind, value FROM publication_identifiers WHERE publication_id = ? ORDER BY kind, value",
                (row["id"],),
            ).fetchall()
        ]
    if include_extra_fields:
        publication["extra_fields"] = [
            dict(field)
            for field in connection.execute(
                "SELECT field_name, field_value, position FROM publication_fields WHERE publication_id = ? ORDER BY field_name, position",
                (row["id"],),
            ).fetchall()
        ]
    connection.close()
    return publication


def _contributors_for_publication(
    connection: sqlite3.Connection, publication_id: int
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT c.name, pc.role, pc.position
        FROM publication_contributors pc
        JOIN contributors c ON c.id = pc.contributor_id
        WHERE pc.publication_id = ?
        ORDER BY CASE pc.role WHEN 'author' THEN 0 ELSE 1 END, pc.position
        """,
        (publication_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _venues_for_publication(
    connection: sqlite3.Connection, publication_id: int
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT v.name, pv.relation_type, pv.position
        FROM publication_venues pv
        JOIN venues v ON v.id = pv.venue_id
        WHERE pv.publication_id = ?
        ORDER BY pv.relation_type, pv.position
        """,
        (publication_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _abstract_for_publication(
    connection: sqlite3.Connection,
    publication_id: int,
) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT abstract_text, provider, source_url, fetched_at
        FROM publication_abstracts
        WHERE publication_id = ?
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "text": row["abstract_text"],
        "provider": row["provider"],
        "source_url": row["source_url"],
        "fetched_at": row["fetched_at"],
    }


def _fulltext_for_publication(
    connection: sqlite3.Connection,
    publication_id: int,
) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT provider, source_url, pdf_url, local_pdf_path, sha256, size_bytes, page_count, image_status, fetched_at
        FROM publication_fulltexts
        WHERE publication_id = ?
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    payload["local_pdf_path"] = relative_to_data_dir(payload["local_pdf_path"])
    return payload


def get_database_status(database_path: str | Path) -> dict[str, object]:
    """Return high-level database status and row counts.

    This is intended as an operational probe for MCP clients and developers who
    need to confirm that the expected SQLite file exists and contains imported
    DBLP data plus abstract enrichment state.
    """
    database = Path(database_path)
    status: dict[str, object] = {
        "database_path": (display_path(database)),
        "exists": database.exists(),
        "data_dir_configured": data_dir_was_explicitly_configured(),
    }
    if not database.exists():
        status["size_bytes"] = None
        status["publications"] = 0
        status["contributors"] = 0
        status["abstracts"] = 0
        status["abstract_fetch_logs"] = 0
        status["fulltexts"] = 0
        status["fulltext_fetch_logs"] = 0
        status["import_runs"] = []
        return status

    status["size_bytes"] = database.stat().st_size
    connection = connect(database)
    try:
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)
        connection.commit()
        status["publications"] = connection.execute(
            "SELECT COUNT(*) FROM publications"
        ).fetchone()[0]
        status["contributors"] = connection.execute(
            "SELECT COUNT(*) FROM contributors"
        ).fetchone()[0]
        status["abstracts"] = connection.execute(
            "SELECT COUNT(*) FROM publication_abstracts"
        ).fetchone()[0]
        status["abstract_fetch_logs"] = connection.execute(
            "SELECT COUNT(*) FROM abstract_fetch_logs"
        ).fetchone()[0]
        status["fulltexts"] = connection.execute(
            "SELECT COUNT(*) FROM publication_fulltexts"
        ).fetchone()[0]
        status["fulltext_fetch_logs"] = connection.execute(
            "SELECT COUNT(*) FROM fulltext_fetch_logs"
        ).fetchone()[0]
        status["import_runs"] = [
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "status": row["status"],
                "records_processed": row["records_processed"],
            }
            for row in connection.execute("""
                SELECT id, started_at, completed_at, status, records_processed
                FROM import_runs
                ORDER BY id DESC
                LIMIT 5
                """).fetchall()
        ]
    finally:
        connection.close()
    return status
