"""Runtime configuration and path-sandbox helpers for the DBLP MCP server."""

from __future__ import annotations

import os
import random
import time
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
ABSTRACT_NETWORK_ENABLED = os.getenv(
    "DBLP_MCP_ENABLE_ABSTRACT_NETWORK", "1"
).strip().casefold() not in {"0", "false", "no", "off"}
FULLTEXT_NETWORK_ENABLED = os.getenv(
    "DBLP_MCP_ENABLE_FULLTEXT_NETWORK", "1"
).strip().casefold() not in {"0", "false", "no", "off"}
ABSTRACT_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_ABSTRACT_TIMEOUT_SECONDS", "30"))
FULLTEXT_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_FULLTEXT_TIMEOUT_SECONDS", "60"))
DOWNLOAD_TIMEOUT_SECONDS = int(os.getenv("DBLP_MCP_DOWNLOAD_TIMEOUT_SECONDS", "60"))
MAX_FULLTEXT_PDF_BYTES = int(
    os.getenv("DBLP_MCP_MAX_FULLTEXT_PDF_BYTES", str(25 * 1024 * 1024))
)
MAX_ABSTRACT_BATCH_SIZE = int(os.getenv("DBLP_MCP_MAX_ABSTRACT_BATCH_SIZE", "100"))
MAX_FULLTEXT_BATCH_SIZE = int(os.getenv("DBLP_MCP_MAX_FULLTEXT_BATCH_SIZE", "50"))
PROVIDER_DELAY_MIN_SECONDS = float(
    os.getenv("DBLP_MCP_PROVIDER_DELAY_MIN_SECONDS", "0.15")
)
PROVIDER_DELAY_MAX_SECONDS = float(
    os.getenv("DBLP_MCP_PROVIDER_DELAY_MAX_SECONDS", "0.6")
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


def ensure_abstract_network_enabled() -> None:
    """Fail fast when abstract-network enrichment has been disabled by config."""
    ensure_network_enabled()
    if not ABSTRACT_NETWORK_ENABLED:
        raise RuntimeError(
            "abstract network access is disabled by DBLP_MCP_ENABLE_ABSTRACT_NETWORK"
        )


def ensure_fulltext_network_enabled() -> None:
    """Fail fast when fulltext-network enrichment has been disabled by config."""
    ensure_network_enabled()
    if not FULLTEXT_NETWORK_ENABLED:
        raise RuntimeError(
            "fulltext network access is disabled by DBLP_MCP_ENABLE_FULLTEXT_NETWORK"
        )


def display_path(path: str | os.PathLike[str]) -> str:
    """Return a safe display path, relative when inside data dir, else basename."""
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    base = DEFAULT_DATA_DIR.resolve()
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        return resolved.name


def provider_request_delay(provider_name: str) -> None:
    """Sleep for a small randomized per-provider delay before requests."""
    key = provider_name.upper().replace("-", "_")
    lower = float(
        os.getenv(
            f"DBLP_MCP_PROVIDER_DELAY_{key}_MIN_SECONDS",
            str(PROVIDER_DELAY_MIN_SECONDS),
        )
    )
    upper = float(
        os.getenv(
            f"DBLP_MCP_PROVIDER_DELAY_{key}_MAX_SECONDS",
            str(PROVIDER_DELAY_MAX_SECONDS),
        )
    )
    lower = max(0.0, lower)
    upper = max(lower, upper)
    time.sleep(random.uniform(lower, upper))
