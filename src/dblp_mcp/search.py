"""Query helpers for the imported DBLP SQLite database.

This module contains read-side operations only: full-text search, detailed
publication lookup, and database status reporting.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .config import data_dir_was_explicitly_configured, relative_to_data_dir
from .database import connect, ensure_abstract_schema, ensure_fulltext_schema
from .text import normalize_for_search

_YEAR_TOKEN_RE = re.compile(r"^(19|20)\d{2}$")


def _split_query_terms(query: str) -> tuple[list[str], list[int]]:
    """Split text tokens from year-like tokens embedded in a search query."""
    text_tokens = []
    years = []
    for token in query.split():
        cleaned = token.strip()
        if not cleaned:
            continue
        normalized = cleaned.strip(",.:;()[]{}")
        if _YEAR_TOKEN_RE.match(normalized):
            years.append(int(normalized))
        else:
            text_tokens.append(normalized)
    return text_tokens, years


def _escape_fts_query(query: str) -> str:
    """Escape user tokens into a conservative SQLite FTS ``AND`` query."""
    tokens = [token.strip() for token in query.split() if token.strip()]
    if not tokens:
        raise ValueError("query must not be empty")
    sanitized_tokens = [token.replace(chr(34), "") for token in tokens]
    return " AND ".join(f'"{token}"' for token in sanitized_tokens)


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
    query: str,
    *,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    record_types: list[str] | None = None,
    contributor: str | None = None,
    venue: str | None = None,
) -> dict[str, object]:
    """Search publications by full-text query plus optional structured filters.

    The query parser treats year-like tokens as year filters and ranks
    paper-like records ahead of proceedings volumes so common venue/year
    searches surface individual papers first.
    """
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    text_tokens, query_years = _split_query_terms(query)
    if not text_tokens and not query_years:
        raise ValueError("query must not be empty")
    effective_year_from = year_from
    effective_year_to = year_to
    if query_years:
        inferred_year_from = min(query_years)
        inferred_year_to = max(query_years)
        effective_year_from = (
            inferred_year_from
            if effective_year_from is None
            else max(effective_year_from, inferred_year_from)
        )
        effective_year_to = (
            inferred_year_to
            if effective_year_to is None
            else min(effective_year_to, inferred_year_to)
        )

    fts_query = _escape_fts_query(" ".join(text_tokens)) if text_tokens else None

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
    results = [
        {
            "dblp_key": row["dblp_key"],
            "record_type": row["record_type"],
            "title": row["title"],
            "year": row["year"],
            "score": row["score"],
            "contributors": _contributors_for_publication(connection, row["id"]),
            "venues": _venues_for_publication(connection, row["id"]),
        }
        for row in rows
    ]
    connection.close()
    return {"query": query, "count": len(results), "results": results}


def get_publication(
    database_path: str | Path, dblp_key: str
) -> dict[str, object] | None:
    """Load one publication and its related normalized records.

    The returned payload includes contributors, venues, identifiers, extra
    fields, and cached abstract data when available.
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

    publication = {
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
        "fulltext": _fulltext_for_publication(connection, row["id"]),
        "identifiers": [
            dict(identifier)
            for identifier in connection.execute(
                "SELECT kind, value FROM publication_identifiers WHERE publication_id = ? ORDER BY kind, value",
                (row["id"],),
            ).fetchall()
        ],
        "extra_fields": [
            dict(field)
            for field in connection.execute(
                "SELECT field_name, field_value, position FROM publication_fields WHERE publication_id = ? ORDER BY field_name, position",
                (row["id"],),
            ).fetchall()
        ],
    }
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
        "database_path": str(database),
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
        status["import_runs"] = [dict(row) for row in connection.execute("""
                SELECT id, source_path, started_at, completed_at, status, records_processed
                FROM import_runs
                ORDER BY id DESC
                LIMIT 5
                """).fetchall()]
    finally:
        connection.close()
    return status
