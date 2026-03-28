from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..config import FULLTEXT_TIMEOUT_SECONDS, MAX_FULLTEXT_PDF_BYTES, ensure_network_enabled, relative_to_data_dir
from ..database import connect, ensure_fulltext_schema
from ..text import normalize_text
from .base import FulltextLookup
from .extract import extract_pdf_artifacts
from .registry import get_providers
from .storage import ensure_storage_dir, hash_file, write_pdf_atomically

USER_AGENT = "dblp-mcp/0.1 (transparent lawful fulltext fetcher; contact repository owner)"
_ALLOWED_PDF_HOSTS = {
    "export.arxiv.org",
    "arxiv.org",
    "ieeexplore.ieee.org",
    "dl.acm.org",
}


def fetch_publication_fulltext(
    database_path: str | Path,
    dblp_key: str,
    *,
    refresh: bool = False,
) -> dict[str, object]:
    connection = connect(database_path)
    try:
        ensure_fulltext_schema(connection)
        row = connection.execute("SELECT id FROM publications WHERE dblp_key = ?", (dblp_key,)).fetchone()
        if row is None:
            raise LookupError(f"publication not found for dblp_key: {dblp_key}")
        publication_id = int(row["id"])

        if not refresh:
            cached = _get_cached_fulltext(connection, publication_id)
            if cached is not None:
                return {"dblp_key": dblp_key, "refresh": refresh, "status": "cached", "fulltext": cached}

        lookup = _build_lookup(connection, publication_id)
        providers = get_providers(lookup)
        if not providers:
            _log_fetch_attempt(connection, publication_id, dblp_key, "unavailable", None, "unsupported", "unsupported_source", "publication does not expose a supported fulltext lookup identifier")
            connection.commit()
            return {"dblp_key": dblp_key, "refresh": refresh, "status": "unsupported", "fulltext": None}

        for provider in providers:
            candidates = provider.fetch_candidates(lookup)
            if not candidates:
                _log_fetch_attempt(connection, publication_id, dblp_key, provider.name, None, "not_found", "not_found", "provider did not return a legal pdf candidate")
                continue
            for candidate in candidates:
                try:
                    stored = _download_and_store_fulltext(connection, publication_id, dblp_key, candidate.provider, candidate.source_url, candidate.pdf_url, candidate.request_headers)
                except Exception as exc:
                    _log_fetch_attempt(connection, publication_id, dblp_key, candidate.provider, candidate.pdf_url, "error", exc.__class__.__name__, str(exc))
                    continue
                _log_fetch_attempt(connection, publication_id, dblp_key, candidate.provider, candidate.pdf_url, "success", None, None)
                connection.commit()
                return {"dblp_key": dblp_key, "refresh": refresh, "status": "fetched", "fulltext": stored}

        connection.commit()
        return {"dblp_key": dblp_key, "refresh": refresh, "status": "not_found", "fulltext": None}
    finally:
        connection.close()


def fetch_publication_fulltexts(database_path: str | Path, dblp_keys: list[str], *, refresh: bool = False) -> dict[str, object]:
    if not dblp_keys:
        raise ValueError("dblp_keys must not be empty")
    results = []
    summary = {"requested": len(dblp_keys), "fetched": 0, "cached": 0, "unsupported": 0, "not_found": 0, "missing": 0, "error": 0}
    for dblp_key in dblp_keys:
        try:
            result = fetch_publication_fulltext(database_path, dblp_key, refresh=refresh)
        except LookupError as exc:
            result = {"dblp_key": dblp_key, "refresh": refresh, "status": "missing", "fulltext": None, "error": str(exc)}
        except Exception as exc:
            result = {"dblp_key": dblp_key, "refresh": refresh, "status": "error", "fulltext": None, "error": str(exc)}
        status = str(result["status"])
        summary[status if status in summary else "error"] += 1
        results.append(result)
    return {"refresh": refresh, "summary": summary, "results": results}


def _build_lookup(connection: sqlite3.Connection, publication_id: int) -> FulltextLookup:
    identifiers = [dict(row) for row in connection.execute("SELECT kind, value FROM publication_identifiers WHERE publication_id = ? ORDER BY kind, value", (publication_id,)).fetchall()]
    extra_fields = [dict(row) for row in connection.execute("SELECT field_name, field_value FROM publication_fields WHERE publication_id = ? ORDER BY field_name, position", (publication_id,)).fetchall()]
    doi = None
    arxiv_id = None
    for identifier in identifiers:
        value = str(identifier["value"])
        doi = doi or _extract_doi(value)
        arxiv_id = arxiv_id or _extract_arxiv_id(value)
    for field in extra_fields:
        value = str(field["field_value"])
        doi = doi or _extract_doi(value)
        arxiv_id = arxiv_id or _extract_arxiv_id(value)
    return FulltextLookup(doi=doi, arxiv_id=arxiv_id)


def _extract_doi(value: str) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    lowered = normalized.casefold()
    marker = "doi.org/"
    if marker in lowered:
        return normalized[lowered.index(marker) + len(marker):].strip() or None
    if lowered.startswith("10.") and "/" in normalized:
        return normalized
    return None


def _extract_arxiv_id(value: str) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    lowered = normalized.casefold()
    marker = "arxiv.org/abs/"
    if marker in lowered:
        return normalized[lowered.index(marker) + len(marker):].strip() or None
    if lowered.startswith("arxiv:"):
        return normalized.split(":", 1)[1].strip() or None
    if lowered.startswith("10.48550/arxiv."):
        return normalized.split("arxiv.", 1)[1].strip() or None
    if lowered.replace('.', '', 1).replace('v', '').isdigit():
        return normalized
    return None


def _download_and_store_fulltext(connection: sqlite3.Connection, publication_id: int, dblp_key: str, provider: str, source_url: str, pdf_url: str, request_headers: dict[str, str] | None = None) -> dict[str, object]:
    parsed = urlparse(pdf_url)
    if parsed.scheme != 'https' or parsed.netloc not in _ALLOWED_PDF_HOSTS:
        raise ValueError('pdf candidate host is not allowlisted')

    headers = {"User-Agent": USER_AGENT}
    if request_headers:
        headers.update(request_headers)
    ensure_network_enabled()
    request = Request(pdf_url, headers=headers)
    with urlopen(request, timeout=FULLTEXT_TIMEOUT_SECONDS) as response:
        final_url = response.geturl() if hasattr(response, 'geturl') else pdf_url
        final = urlparse(final_url)
        if final.scheme != 'https' or final.netloc not in _ALLOWED_PDF_HOSTS:
            raise ValueError('pdf download redirected to an unexpected host')
        content_length = response.headers.get('Content-Length', '') if hasattr(response, 'headers') else ''
        if content_length.isdigit() and int(content_length) > MAX_FULLTEXT_PDF_BYTES:
            raise ValueError('pdf exceeds configured size limit')
        payload = response.read(MAX_FULLTEXT_PDF_BYTES + 1)
        content_type = response.headers.get('Content-Type', '') if hasattr(response, 'headers') else ''
    if len(payload) > MAX_FULLTEXT_PDF_BYTES:
        raise ValueError('pdf exceeds configured size limit')
    if payload.lstrip().startswith(b'<!DOCTYPE html') or payload.lstrip().startswith(b'<html'):
        raise ValueError('downloaded content is html rather than a pdf')
    if not payload.startswith(b'%PDF') and 'pdf' not in content_type.casefold():
        raise ValueError('downloaded content is not a pdf')

    storage_dir = ensure_storage_dir(dblp_key)
    pdf_path = storage_dir / 'fulltext.pdf'
    write_pdf_atomically(pdf_path, payload)
    artifacts = extract_pdf_artifacts(pdf_path)
    sha256 = hash_file(pdf_path)
    fetched_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO publication_fulltexts(
            publication_id, provider, source_url, pdf_url, local_pdf_path,
            sha256, size_bytes, page_count, full_text, full_text_norm,
            image_status, page_image_paths_json, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(publication_id) DO UPDATE SET
            provider=excluded.provider, source_url=excluded.source_url, pdf_url=excluded.pdf_url,
            local_pdf_path=excluded.local_pdf_path, sha256=excluded.sha256, size_bytes=excluded.size_bytes,
            page_count=excluded.page_count, full_text=excluded.full_text, full_text_norm=excluded.full_text_norm,
            image_status=excluded.image_status, page_image_paths_json=excluded.page_image_paths_json,
            fetched_at=excluded.fetched_at
        """,
        (publication_id, provider, source_url, pdf_url, str(pdf_path), sha256, pdf_path.stat().st_size, artifacts.page_count, artifacts.full_text, artifacts.full_text_norm, artifacts.image_status, json.dumps(artifacts.page_image_paths), fetched_at),
    )
    return _get_cached_fulltext(connection, publication_id) or {}


def _get_cached_fulltext(connection: sqlite3.Connection, publication_id: int) -> dict[str, object] | None:
    row = connection.execute("SELECT provider, source_url, pdf_url, local_pdf_path, sha256, size_bytes, page_count, full_text, image_status, page_image_paths_json, fetched_at FROM publication_fulltexts WHERE publication_id = ?", (publication_id,)).fetchone()
    if row is None:
        return None
    return {
        'provider': row['provider'],
        'source_url': row['source_url'],
        'pdf_url': row['pdf_url'],
        'local_pdf_path': relative_to_data_dir(row['local_pdf_path']),
        'sha256': row['sha256'],
        'size_bytes': row['size_bytes'],
        'page_count': row['page_count'],
        'text': row['full_text'],
        'image_status': row['image_status'],
        'page_image_paths': [relative_to_data_dir(item) for item in json.loads(row['page_image_paths_json'] or '[]')],
        'fetched_at': row['fetched_at'],
    }


def _sanitize_error_message(error_message: str | None) -> str | None:
    if error_message is None:
        return None
    normalized = normalize_text(error_message)
    return normalized[:500] if normalized else None


def _log_fetch_attempt(connection: sqlite3.Connection, publication_id: int | None, dblp_key: str | None, provider: str, attempted_url: str | None, status: str, error_code: str | None, error_message: str | None) -> None:
    connection.execute(
        "INSERT INTO fulltext_fetch_logs(publication_id, dblp_key, provider, attempted_url, status, error_code, error_message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (publication_id, dblp_key, provider, attempted_url, status, error_code, _sanitize_error_message(error_message), datetime.now(timezone.utc).isoformat()),
    )
