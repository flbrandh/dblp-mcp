from __future__ import annotations

from pathlib import Path
import sqlite3

from .config import relative_to_data_dir
from .database import connect, ensure_abstract_schema, ensure_fulltext_schema


def get_recent_fetch_failures(
    database_path: str | Path,
    *,
    category: str = "all",
    limit: int = 20,
) -> dict[str, object]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if category not in {"all", "abstract", "fulltext"}:
        raise ValueError("category must be one of: all, abstract, fulltext")

    connection = connect(database_path)
    try:
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)
        connection.commit()
        entries: list[dict[str, object]] = []
        remaining = limit
        if category in {"all", "abstract"}:
            entries.extend(_abstract_failures(connection, limit if category == "abstract" else limit))
        if category in {"all", "fulltext"}:
            entries.extend(_fulltext_failures(connection, limit if category == "fulltext" else limit))
        entries.sort(key=lambda item: str(item["created_at"]), reverse=True)
        entries = entries[:limit]
        return {"category": category, "count": len(entries), "results": entries}
    finally:
        connection.close()


def _abstract_failures(connection: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT dblp_key, provider, attempted_url, status, error_code, error_message, created_at
        FROM abstract_fetch_logs
        WHERE status != 'success'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) | {"category": "abstract"} for row in rows]


def _fulltext_failures(connection: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT dblp_key, provider, attempted_url, status, error_code, error_message, created_at
        FROM fulltext_fetch_logs
        WHERE status != 'success'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) | {"category": "fulltext"} for row in rows]
