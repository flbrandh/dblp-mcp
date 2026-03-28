"""Runtime configuration and path-sandbox helpers for the DBLP MCP server."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SOURCE_URL = "https://dblp.org/xml/dblp.xml.gz"
_DBLP_MCP_DATA_DIR = os.getenv("DBLP_MCP_DATA_DIR")
DEFAULT_DATA_DIR = (
    Path(_DBLP_MCP_DATA_DIR).expanduser().resolve()
    if _DBLP_MCP_DATA_DIR
    else (Path.cwd() / "data").resolve()
)
DEFAULT_XML_PATH = DEFAULT_DATA_DIR / "dblp.xml.gz"
DEFAULT_DATABASE_PATH = DEFAULT_DATA_DIR / "dblp.sqlite"
DEFAULT_BATCH_SIZE = int(os.getenv("DBLP_MCP_BATCH_SIZE", "500"))
DEFAULT_FULLTEXT_DIR = DEFAULT_DATA_DIR / "fulltext"
NETWORK_ENABLED = os.getenv("DBLP_MCP_ENABLE_NETWORK", "1").strip().casefold() not in {
    "0",
    "false",
    "no",
    "off",
}
ABSTRACT_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_ABSTRACT_TIMEOUT_SECONDS", "30"))
FULLTEXT_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_FULLTEXT_TIMEOUT_SECONDS", "60"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_DOWNLOAD_TIMEOUT_SECONDS", "60"))
MAX_FULLTEXT_PDF_BYTES = int(
    os.getenv("DBLP_MCP_MAX_FULLTEXT_PDF_BYTES", str(25 * 1024 * 1024))
)


def data_dir_was_explicitly_configured() -> bool:
    """Return whether `DBLP_MCP_DATA_DIR` was set in the environment."""
    return _DBLP_MCP_DATA_DIR is not None


def ensure_network_enabled() -> None:
    """Fail fast when network-backed enrichment has been disabled by config."""
    if not NETWORK_ENABLED:
        raise RuntimeError(
            "network-backed enrichment is disabled by DBLP_MCP_ENABLE_NETWORK"
        )


def resolve_data_path(path: str | os.PathLike[str]) -> Path:
    """Resolve a path and ensure it stays within ``DBLP_MCP_DATA_DIR``.

    Relative paths are interpreted under the configured data directory. Absolute
    paths are allowed only when they remain inside the same directory tree.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = DEFAULT_DATA_DIR / candidate
    resolved = candidate.resolve(strict=False)
    base = DEFAULT_DATA_DIR.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path must stay within DBLP_MCP_DATA_DIR: {base}") from exc
    return resolved


def relative_to_data_dir(path: str | os.PathLike[str]) -> str:
    """Return a path relative to ``DBLP_MCP_DATA_DIR`` for safe client output."""
    resolved = resolve_data_path(path)
    return str(resolved.relative_to(DEFAULT_DATA_DIR))
