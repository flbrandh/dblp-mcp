"""Orchestration logic for provider-based abstract fetching.

The service resolves a publication from the local DBLP SQLite database, derives
lookup identifiers such as DOI or arXiv ID, chooses matching providers, caches
successful abstracts, and records operational logs for all outcomes.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

from ..config import MAX_ABSTRACT_BATCH_SIZE
from ..database import connect, ensure_abstract_schema
from ..text import normalize_text
from .base import AbstractFetchResult, AbstractLookup
from .registry import get_providers

_ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$",
    re.IGNORECASE,
)


class AbstractPayload(TypedDict):
    text: str
    provider: str
    source_url: str
    fetched_at: str


class AbstractResult(TypedDict, total=False):
    dblp_key: str
    refresh: bool
    status: str
    abstract: AbstractPayload | None


@dataclass(slots=True)
class _PublicationContext:
    publication_id: int
    dblp_key: str
    identifiers: list[dict[str, str]]
    extra_fields: list[dict[str, object]]


def fetch_publication_abstract(
    database_path: str | Path,
    dblp_key: str,
    *,
    refresh: bool = False,
) -> dict[str, object]:
    """Fetch an abstract for one imported publication and cache the result.

    The function first checks for an existing cached abstract unless
    ``refresh=True``. If no cached value exists, it derives lookup identifiers
    from the stored publication metadata, tries matching providers in registry
    order, stores the first successful abstract, and logs every outcome for
    later debugging.
    """
    connection = connect(database_path)
    try:
        ensure_abstract_schema(connection)
        publication = _load_publication_context(connection, dblp_key)
        if publication is None:
            raise LookupError(f"publication not found for dblp_key: {dblp_key}")

        if not refresh:
            cached_abstract = _get_stored_abstract(
                connection, publication.publication_id
            )
            if cached_abstract is not None:
                return {
                    "dblp_key": dblp_key,
                    "refresh": refresh,
                    "status": "cached",
                    "abstract": cached_abstract,
                }

        lookup = _build_lookup(publication)
        providers = get_providers(lookup)
        if not providers:
            _log_fetch_attempt(
                connection,
                publication_id=publication.publication_id,
                dblp_key=publication.dblp_key,
                provider="unavailable",
                attempted_url=None,
                status="unsupported",
                error_code="unsupported_source",
                error_message="publication does not expose a supported abstract lookup identifier",
            )
            connection.commit()
            return {
                "dblp_key": dblp_key,
                "refresh": refresh,
                "status": "unsupported",
                "abstract": None,
            }

        for provider in providers:
            attempted_url = provider.build_attempted_url(lookup)
            try:
                result = provider.fetch(lookup)
            except Exception as exc:
                _log_fetch_attempt(
                    connection,
                    publication_id=publication.publication_id,
                    dblp_key=publication.dblp_key,
                    provider=provider.name,
                    attempted_url=attempted_url,
                    status="error",
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
                continue

            if result is None:
                _log_fetch_attempt(
                    connection,
                    publication_id=publication.publication_id,
                    dblp_key=publication.dblp_key,
                    provider=provider.name,
                    attempted_url=attempted_url,
                    status="not_found",
                    error_code="not_found",
                    error_message="provider did not return an abstract",
                )
                continue

            stored_abstract = _store_abstract(
                connection, publication.publication_id, result
            )
            _log_fetch_attempt(
                connection,
                publication_id=publication.publication_id,
                dblp_key=publication.dblp_key,
                provider=provider.name,
                attempted_url=result.source_url,
                status="success",
                error_code=None,
                error_message=None,
            )
            connection.commit()
            return {
                "dblp_key": dblp_key,
                "refresh": refresh,
                "status": "fetched",
                "abstract": stored_abstract,
            }

        connection.commit()
        return {
            "dblp_key": dblp_key,
            "refresh": refresh,
            "status": "not_found",
            "abstract": None,
        }
    finally:
        connection.close()


def fetch_publication_abstracts(
    database_path: str | Path,
    dblp_keys: list[str],
    *,
    refresh: bool = False,
) -> dict[str, object]:
    """Fetch abstracts for multiple imported publications.

    Each requested DBLP key is processed independently so one missing publication
    or unsupported source does not prevent other fetches from succeeding.
    """
    if not dblp_keys:
        raise ValueError("dblp_keys must not be empty")
    if len(dblp_keys) > MAX_ABSTRACT_BATCH_SIZE:
        raise ValueError(
            f"dblp_keys must contain at most {MAX_ABSTRACT_BATCH_SIZE} entries"
        )

    results: list[dict[str, object]] = []
    summary = {
        "requested": len(dblp_keys),
        "fetched": 0,
        "cached": 0,
        "unsupported": 0,
        "not_found": 0,
        "missing": 0,
        "error": 0,
    }

    for dblp_key in dblp_keys:
        try:
            result = fetch_publication_abstract(
                database_path=database_path,
                dblp_key=dblp_key,
                refresh=refresh,
            )
        except LookupError as exc:
            result = {
                "dblp_key": dblp_key,
                "refresh": refresh,
                "status": "missing",
                "abstract": None,
                "error": str(exc),
            }
        except Exception as exc:
            result = {
                "dblp_key": dblp_key,
                "refresh": refresh,
                "status": "error",
                "abstract": None,
                "error": str(exc),
            }

        status = str(result["status"])
        if status in summary:
            summary[status] += 1
        else:
            summary["error"] += 1
        results.append(result)

    return {
        "refresh": refresh,
        "summary": summary,
        "results": results,
    }


def _load_publication_context(
    connection: sqlite3.Connection,
    dblp_key: str,
) -> _PublicationContext | None:
    row = connection.execute(
        "SELECT id, dblp_key FROM publications WHERE dblp_key = ?",
        (dblp_key,),
    ).fetchone()
    if row is None:
        return None

    identifiers = [
        {"kind": str(identifier["kind"]), "value": str(identifier["value"])}
        for identifier in connection.execute(
            "SELECT kind, value FROM publication_identifiers WHERE publication_id = ? ORDER BY kind, value",
            (row["id"],),
        ).fetchall()
    ]
    extra_fields = [
        dict(field)
        for field in connection.execute(
            "SELECT field_name, field_value, position FROM publication_fields WHERE publication_id = ? ORDER BY field_name, position",
            (row["id"],),
        ).fetchall()
    ]
    return _PublicationContext(
        publication_id=int(row["id"]),
        dblp_key=str(row["dblp_key"]),
        identifiers=identifiers,
        extra_fields=extra_fields,
    )


def _build_lookup(publication: _PublicationContext) -> AbstractLookup:
    """Derive provider lookup identifiers from stored DBLP metadata."""
    doi: str | None = None
    arxiv_id: str | None = None

    for identifier in publication.identifiers:
        value = normalize_text(identifier["value"])
        if doi is None:
            doi = _extract_doi(value)
        if arxiv_id is None:
            arxiv_id = _extract_arxiv_id(value)

    for field in publication.extra_fields:
        field_name = str(field["field_name"]).casefold()
        field_value = normalize_text(str(field["field_value"]))
        if field_name in {"eprint", "arxiv"} and arxiv_id is None:
            arxiv_id = _extract_arxiv_id(field_value) or field_value

    return AbstractLookup(doi=doi, arxiv_id=arxiv_id)


def _extract_doi(value: str) -> str | None:
    """Extract a DOI from DBLP identifier text or DOI URL forms."""
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.casefold()
    prefixes = (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    if "/" in normalized and " " not in normalized:
        return normalized
    return None


def _extract_arxiv_id(value: str) -> str | None:
    """Extract an arXiv identifier from common URL and DOI forms."""
    normalized = value.strip()
    if not normalized:
        return None

    lowered = normalized.casefold()
    if lowered.startswith("10.48550/arxiv."):
        return normalized.split("/", 1)[1].split(".", 1)[1]
    if "arxiv.org" in lowered:
        path = urlparse(normalized).path.strip("/")
        if path.startswith("abs/"):
            return path.removeprefix("abs/")
        if path.startswith("pdf/"):
            return path.removeprefix("pdf/").removesuffix(".pdf")
    if normalized.lower().startswith("arxiv:"):
        return normalized.split(":", 1)[1].strip()
    return normalized if _ARXIV_ID_RE.match(normalized) else None


def _get_stored_abstract(
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


def _store_abstract(
    connection: sqlite3.Connection,
    publication_id: int,
    result: AbstractFetchResult,
) -> dict[str, object]:
    fetched_at = datetime.now(UTC).isoformat()
    connection.execute(
        """
        INSERT INTO publication_abstracts(
            publication_id,
            abstract_text,
            abstract_norm,
            provider,
            source_url,
            fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(publication_id) DO UPDATE SET
            abstract_text = excluded.abstract_text,
            abstract_norm = excluded.abstract_norm,
            provider = excluded.provider,
            source_url = excluded.source_url,
            fetched_at = excluded.fetched_at
        """,
        (
            publication_id,
            result.abstract_text,
            result.abstract_norm,
            result.provider,
            result.source_url,
            fetched_at,
        ),
    )
    return {
        "text": result.abstract_text,
        "provider": result.provider,
        "source_url": result.source_url,
        "fetched_at": fetched_at,
    }


def _sanitize_error_message(error_message: str | None) -> str | None:
    if error_message is None:
        return None
    normalized = normalize_text(error_message)
    return normalized[:500] if normalized else None


def _log_fetch_attempt(
    connection: sqlite3.Connection,
    *,
    publication_id: int | None,
    dblp_key: str | None,
    provider: str,
    attempted_url: str | None,
    status: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO abstract_fetch_logs(
            publication_id,
            dblp_key,
            provider,
            attempted_url,
            status,
            error_code,
            error_message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            publication_id,
            dblp_key,
            provider,
            attempted_url,
            status,
            error_code,
            _sanitize_error_message(error_message),
            datetime.now(UTC).isoformat(),
        ),
    )
