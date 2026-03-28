"""Filesystem helpers for cached full-text PDFs and derived artifacts."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from ..config import DEFAULT_DATA_DIR

FULLTEXT_ROOT = DEFAULT_DATA_DIR / "fulltext"


def publication_storage_dir(dblp_key: str) -> Path:
    """Return the cache directory used for one publication key."""
    safe_key = dblp_key.replace("/", "__")
    return FULLTEXT_ROOT / safe_key


def ensure_storage_dir(dblp_key: str) -> Path:
    """Create and return the cache directory for one publication key."""
    path = publication_storage_dir(dblp_key)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_pdf_atomically(destination: Path, payload: bytes) -> None:
    """Write PDF bytes via a temporary file and atomic replace."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    temp_path.write_bytes(payload)
    os.replace(temp_path, destination)


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 digest of a file without loading it fully into memory."""
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
