"""Diagnostics helpers for inspecting enrichment failures."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict, cast

from .database import connect, ensure_abstract_schema, ensure_fulltext_schema


class FailureEntry(TypedDict):
    """One recent abstract/fulltext failure log row returned to clients."""

    category: str
    dblp_key: str | None
    provider: str
    attempted_url_redacted: str | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: str


def _redact_error_message(error_message: str | None) -> str | None:
    """Redact verbose error messages down to a stable short form."""
    if not error_message:
        return None
    lowered = error_message.casefold()
    if "network" in lowered and "disabled" in lowered:
        return "network disabled"
    if "http" in lowered:
        return "http error"
    if "redirect" in lowered:
        return "redirect error"
    if "pdf" in lowered:
        return "pdf validation error"
    return "provider error"


def _redact_url(url: str | None) -> str | None:
    """Redact URLs down to scheme and host for safer diagnostics."""
    if not url:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/..."


def get_recent_fetch_failures(
    database_path: str | Path,
    *,
    category: str = "all",
    limit: int = 20,
) -> dict[str, object]:
    """Return recent non-success abstract/fulltext fetch log entries."""
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if category not in {"all", "abstract", "fulltext"}:
        raise ValueError("category must be one of: all, abstract, fulltext")

    connection = connect(database_path)
    try:
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)
        connection.commit()
        entries: list[FailureEntry] = []
        if category in {"all", "abstract"}:
            entries.extend(_abstract_failures(connection, limit))
        if category in {"all", "fulltext"}:
            entries.extend(_fulltext_failures(connection, limit))
        entries.sort(key=lambda item: item["created_at"], reverse=True)
        entries = entries[:limit]
        return {"category": category, "count": len(entries), "results": entries}
    finally:
        connection.close()


def _abstract_failures(
    connection: sqlite3.Connection, limit: int
) -> list[FailureEntry]:
    """Load recent abstract-provider failures from SQLite."""
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
    return [
        cast(
            FailureEntry,
            {
                "category": "abstract",
                "dblp_key": row["dblp_key"],
                "provider": row["provider"],
                "attempted_url_redacted": _redact_url(row["attempted_url"]),
                "status": row["status"],
                "error_code": row["error_code"],
                "error_message": _redact_error_message(row["error_message"]),
                "created_at": row["created_at"],
            },
        )
        for row in rows
    ]


def _fulltext_failures(
    connection: sqlite3.Connection, limit: int
) -> list[FailureEntry]:
    """Load recent fulltext-provider failures from SQLite."""
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
    return [
        cast(
            FailureEntry,
            {
                "category": "fulltext",
                "dblp_key": row["dblp_key"],
                "provider": row["provider"],
                "attempted_url_redacted": _redact_url(row["attempted_url"]),
                "status": row["status"],
                "error_code": row["error_code"],
                "error_message": _redact_error_message(row["error_message"]),
                "created_at": row["created_at"],
            },
        )
        for row in rows
    ]
