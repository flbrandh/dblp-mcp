"""MCP server exposing DBLP search, status, enrichment, and optional admin tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .abstracts import (
    fetch_publication_abstract as run_fetch_publication_abstract,
    fetch_publication_abstracts as run_fetch_publication_abstracts,
)
from .config import DEFAULT_DATABASE_PATH, DEFAULT_XML_PATH, resolve_data_path
from .diagnostics import get_recent_fetch_failures as run_get_recent_fetch_failures
from .downloader import download_dblp_dump as run_download
from .fulltext import (
    fetch_publication_fulltext as run_fetch_publication_fulltext,
    fetch_publication_fulltexts as run_fetch_publication_fulltexts,
)
from .importer import DblpImporter
from .search import (
    get_database_status as run_get_database_status,
    get_publication as run_get_publication,
    search_publications as run_search,
)


def _sandboxed_database_path(database_path: str) -> str:
    return str(resolve_data_path(database_path))


def _sandboxed_xml_path(xml_path: str) -> str:
    return str(resolve_data_path(xml_path))


def _sandboxed_destination_path(destination: str) -> str:
    return str(resolve_data_path(destination))


def create_mcp(*, privileged: bool = False) -> FastMCP:
    """Create the DBLP MCP server.

    Privileged mode exposes maintenance tools that can download raw DBLP data and
    rebuild the SQLite database. Unprivileged mode exposes read/search and
    enrichment tools only.
    """
    mcp = FastMCP("dblp")

    if privileged:

        @mcp.tool()
        def download_dblp_dump(
            destination: str = str(DEFAULT_XML_PATH),
            source_url: str = "https://dblp.org/xml/dblp.xml.gz",
            replace: bool = False,
        ) -> dict[str, object]:
            """Download a DBLP XML-area artifact to local storage."""
            result = run_download(destination=_sandboxed_destination_path(destination), source_url=source_url, replace=replace)
            return {
                "source_url": result.source_url,
                "destination": str(result.destination),
                "size_bytes": result.size_bytes,
                "sha256": result.sha256,
                "downloaded_at": result.downloaded_at,
                "cached": result.cached,
            }


        @mcp.tool()
        def build_dblp_sqlite(
            xml_path: str = str(DEFAULT_XML_PATH),
            database_path: str = str(DEFAULT_DATABASE_PATH),
            replace: bool = True,
            batch_size: int = 500,
        ) -> dict[str, object]:
            """Build the SQLite search database from a DBLP XML or XML.GZ file."""
            safe_database_path = _sandboxed_database_path(database_path)
            safe_xml_path = _sandboxed_xml_path(xml_path)
            importer = DblpImporter(database_path=safe_database_path, batch_size=batch_size)
            return importer.import_file(xml_path=safe_xml_path, replace=replace)

    @mcp.tool()
    def search_publications(
        query: str,
        database_path: str = str(DEFAULT_DATABASE_PATH),
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
        record_types: list[str] | None = None,
        contributor: str | None = None,
        venue: str | None = None,
    ) -> dict[str, object]:
        """Run full-text and structured search over the imported DBLP database."""
        return run_search(
            database_path=_sandboxed_database_path(database_path),
            query=query,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            record_types=record_types,
            contributor=contributor,
            venue=venue,
        )


    @mcp.tool()
    def get_publication(
        dblp_key: str,
        database_path: str = str(DEFAULT_DATABASE_PATH),
    ) -> dict[str, object] | None:
        """Return one imported publication, including cached enrichment data."""
        return run_get_publication(database_path=_sandboxed_database_path(database_path), dblp_key=dblp_key)


    @mcp.tool()
    def fetch_publication_abstract(
        dblp_key: str,
        database_path: str = str(DEFAULT_DATABASE_PATH),
        refresh: bool = False,
    ) -> dict[str, object]:
        """Fetch and cache an abstract for an imported publication."""
        return run_fetch_publication_abstract(
            database_path=_sandboxed_database_path(database_path),
            dblp_key=dblp_key,
            refresh=refresh,
        )


    @mcp.tool()
    def fetch_publication_abstracts(
        dblp_keys: list[str],
        database_path: str = str(DEFAULT_DATABASE_PATH),
        refresh: bool = False,
    ) -> dict[str, object]:
        """Fetch and cache abstracts for multiple imported publications."""
        return run_fetch_publication_abstracts(
            database_path=_sandboxed_database_path(database_path),
            dblp_keys=dblp_keys,
            refresh=refresh,
        )


    @mcp.tool()
    def fetch_publication_fulltext(
        dblp_key: str,
        database_path: str = str(DEFAULT_DATABASE_PATH),
        refresh: bool = False,
    ) -> dict[str, object]:
        """Fetch and cache a legal full-text PDF plus extracted text for one publication."""
        return run_fetch_publication_fulltext(database_path=_sandboxed_database_path(database_path), dblp_key=dblp_key, refresh=refresh)


    @mcp.tool()
    def fetch_publication_fulltexts(
        dblp_keys: list[str],
        database_path: str = str(DEFAULT_DATABASE_PATH),
        refresh: bool = False,
    ) -> dict[str, object]:
        """Fetch and cache legal full-text PDFs plus extracted text for multiple publications."""
        return run_fetch_publication_fulltexts(database_path=_sandboxed_database_path(database_path), dblp_keys=dblp_keys, refresh=refresh)


    @mcp.tool()
    def get_recent_fetch_failures(
        database_path: str = str(DEFAULT_DATABASE_PATH),
        category: str = "all",
        limit: int = 20,
    ) -> dict[str, object]:
        """Inspect recent abstract/fulltext fetch failures for operator debugging."""
        return run_get_recent_fetch_failures(
            database_path=_sandboxed_database_path(database_path),
            category=category,
            limit=limit,
        )


    @mcp.tool()
    def get_dblp_status(
        database_path: str = str(DEFAULT_DATABASE_PATH),
    ) -> dict[str, object]:
        """Report file existence plus import, abstract, fulltext, and log counters."""
        return run_get_database_status(database_path=_sandboxed_database_path(database_path))

    return mcp


mcp = create_mcp(privileged=False)
