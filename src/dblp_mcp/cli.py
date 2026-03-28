"""Small helper CLI for local operator workflows outside MCP clients."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from .config import DEFAULT_DATABASE_PATH, DEFAULT_XML_PATH
from .downloader import download_dblp_dump
from .importer import DblpImporter
from .search import get_publication, search_publications


def build_parser() -> argparse.ArgumentParser:
    """Create the helper CLI argument parser."""
    parser = argparse.ArgumentParser(description="DBLP MCP helper CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="download the DBLP dump")
    download_parser.add_argument("--destination", default=str(DEFAULT_XML_PATH))
    download_parser.add_argument(
        "--source-url", default="https://dblp.org/xml/dblp.xml.gz"
    )
    download_parser.add_argument("--replace", action="store_true")

    import_parser = subparsers.add_parser("import", help="build the SQLite database")
    import_parser.add_argument("--xml-path", default=str(DEFAULT_XML_PATH))
    import_parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    import_parser.add_argument("--batch-size", default=500, type=int)

    search_parser = subparsers.add_parser("search", help="search the SQLite database")
    search_parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--year-from", type=int)
    search_parser.add_argument("--year-to", type=int)
    search_parser.add_argument("--record-type", action="append", dest="record_types")
    search_parser.add_argument("--contributor")
    search_parser.add_argument("--venue")

    get_parser = subparsers.add_parser("get", help="fetch one publication by DBLP key")
    get_parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    get_parser.add_argument("--dblp-key", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Execute the helper CLI and print structured JSON results."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download":
        download_result = download_dblp_dump(
            destination=args.destination,
            source_url=args.source_url,
            replace=args.replace,
        )
        print(json.dumps(asdict(download_result), indent=2, default=str))
        return

    if args.command == "import":
        importer = DblpImporter(args.database_path, batch_size=args.batch_size)
        import_result = importer.import_file(args.xml_path, replace=True)
        print(json.dumps(import_result, indent=2))
        return

    if args.command == "search":
        search_result = search_publications(
            database_path=args.database_path,
            query=args.query,
            limit=args.limit,
            year_from=args.year_from,
            year_to=args.year_to,
            record_types=args.record_types,
            contributor=args.contributor,
            venue=args.venue,
        )
        print(json.dumps(search_result, indent=2))
        return

    if args.command == "get":
        publication = get_publication(args.database_path, args.dblp_key)
        print(json.dumps(publication, indent=2))
        return

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    main()
