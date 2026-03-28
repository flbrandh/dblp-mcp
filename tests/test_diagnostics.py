from __future__ import annotations

from pathlib import Path

import pytest

from dblp_mcp.abstracts.service import _log_fetch_attempt as log_abstract_attempt
from dblp_mcp.database import connect, ensure_abstract_schema, ensure_fulltext_schema
from dblp_mcp.diagnostics import get_recent_fetch_failures
from dblp_mcp.fulltext.service import _log_fetch_attempt as log_fulltext_attempt
from dblp_mcp.importer import DblpImporter

SAMPLE_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
  <article key="journals/test/Diag2024" mdate="2024-01-01">
    <author>Alice Example</author>
    <title>Diagnostics Test Paper</title>
    <year>2024</year>
    <journal>Journal of Test Data</journal>
  </article>
</dblp>
"""


def test_get_recent_fetch_failures_returns_abstract_and_fulltext_entries(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    dtd_path = tmp_path / "dblp.dtd"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    dtd_path.write_text("", encoding="utf-8")
    DblpImporter(database_path).import_file(xml_path)

    connection = connect(database_path)
    try:
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)
        publication_id = connection.execute(
            "SELECT id FROM publications WHERE dblp_key = ?",
            ("journals/test/Diag2024",),
        ).fetchone()[0]
        log_abstract_attempt(
            connection,
            publication_id=publication_id,
            dblp_key="journals/test/Diag2024",
            provider="openalex",
            attempted_url="https://api.openalex.org/x",
            status="not_found",
            error_code="not_found",
            error_message="no abstract",
        )
        log_fulltext_attempt(
            connection,
            publication_id,
            "journals/test/Diag2024",
            "openalex_pdf",
            "https://example.org/x.pdf",
            "error",
            "HTTPError",
            "bad response",
        )
        connection.commit()
    finally:
        connection.close()

    result = get_recent_fetch_failures(database_path, category="all", limit=10)

    assert result["count"] == 2
    assert {item["category"] for item in result["results"]} == {"abstract", "fulltext"}


def test_get_recent_fetch_failures_validates_arguments(tmp_path: Path) -> None:
    database_path = tmp_path / "dblp.sqlite"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS publications (id INTEGER PRIMARY KEY, dblp_key TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)

    try:
        get_recent_fetch_failures(database_path, category="weird")
    except ValueError as exc:
        assert "category" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_get_recent_fetch_failures_filters_by_category(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    dtd_path = tmp_path / "dblp.dtd"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    dtd_path.write_text("", encoding="utf-8")
    DblpImporter(database_path).import_file(xml_path)

    connection = connect(database_path)
    try:
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)
        publication_id = connection.execute(
            "SELECT id FROM publications WHERE dblp_key = ?",
            ("journals/test/Diag2024",),
        ).fetchone()[0]
        log_abstract_attempt(
            connection,
            publication_id=publication_id,
            dblp_key="journals/test/Diag2024",
            provider="openalex",
            attempted_url="https://api.openalex.org/x",
            status="not_found",
            error_code="not_found",
            error_message="no abstract",
        )
        log_fulltext_attempt(
            connection,
            publication_id,
            "journals/test/Diag2024",
            "openalex_pdf",
            "https://example.org/x.pdf",
            "error",
            "HTTPError",
            "bad response",
        )
        connection.commit()
    finally:
        connection.close()

    abstract_only = get_recent_fetch_failures(
        database_path, category="abstract", limit=10
    )
    fulltext_only = get_recent_fetch_failures(
        database_path, category="fulltext", limit=10
    )

    assert abstract_only["count"] == 1
    assert abstract_only["results"][0]["category"] == "abstract"
    assert fulltext_only["count"] == 1
    assert fulltext_only["results"][0]["category"] == "fulltext"


def test_get_recent_fetch_failures_validates_limits(tmp_path: Path) -> None:
    database_path = tmp_path / "dblp.sqlite"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS publications (id INTEGER PRIMARY KEY, dblp_key TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        ensure_abstract_schema(connection)
        ensure_fulltext_schema(connection)

    with pytest.raises(ValueError, match="limit must be between 1 and 200"):
        get_recent_fetch_failures(database_path, limit=0)
    with pytest.raises(ValueError, match="limit must be between 1 and 200"):
        get_recent_fetch_failures(database_path, limit=201)
