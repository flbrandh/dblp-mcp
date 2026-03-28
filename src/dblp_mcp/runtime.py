"""Command-line runtime entrypoint for launching the MCP server."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .config import data_dir_was_explicitly_configured
from .server import create_mcp


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse runtime flags for privileged mode and implicit data-dir fallback."""
    parser = argparse.ArgumentParser(description="Run the DBLP MCP server")
    parser.add_argument(
        "--privileged",
        action="store_true",
        help="Expose download/build maintenance tools in addition to normal read/search tools",
    )
    parser.add_argument(
        "--allow-implicit-data-dir",
        action="store_true",
        help="Allow fallback to ./data when DBLP_MCP_DATA_DIR is not set",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Launch the stdio MCP server after enforcing runtime safety checks."""
    args = parse_args(argv)
    if not data_dir_was_explicitly_configured() and not args.allow_implicit_data_dir:
        raise SystemExit(
            "DBLP_MCP_DATA_DIR must be set explicitly; use --allow-implicit-data-dir to fall back to ./data"
        )
    create_mcp(privileged=args.privileged).run()
