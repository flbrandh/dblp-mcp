from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from .config import DEFAULT_SOURCE_URL, DOWNLOAD_TIMEOUT_SECONDS, ensure_network_enabled, resolve_data_path


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class DownloadResult:
    source_url: str
    destination: Path
    size_bytes: int
    sha256: str
    downloaded_at: str
    cached: bool


def _validate_source_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme != "https":
        raise ValueError("source_url must use https")
    if parsed.netloc != "dblp.org":
        raise ValueError("source_url must point to dblp.org")
    if not parsed.path.startswith("/xml/"):
        raise ValueError("source_url must point to the DBLP XML area")


def download_dblp_dump(
    destination: str | os.PathLike[str],
    source_url: str = DEFAULT_SOURCE_URL,
    *,
    replace: bool = False,
    chunk_size: int = 1024 * 1024,
    timeout_seconds: int = DOWNLOAD_TIMEOUT_SECONDS,
) -> DownloadResult:
    ensure_network_enabled()
    _validate_source_url(source_url)
    destination_path = resolve_data_path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if destination_path.exists() and not replace:
        digest = _hash_file(destination_path, chunk_size=chunk_size)
        return DownloadResult(
            source_url=source_url,
            destination=destination_path,
            size_bytes=destination_path.stat().st_size,
            sha256=digest,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            cached=True,
        )

    temp_path = destination_path.with_suffix(destination_path.suffix + ".part")
    digest = sha256()
    size_bytes = 0

    try:
        with urlopen(source_url, timeout=timeout_seconds) as response, temp_path.open("wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
    except HTTPError as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"DBLP download failed with HTTP status {exc.code}") from exc
    except URLError as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"DBLP download failed: {exc.reason}") from exc
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Unable to store DBLP dump at {destination_path}: {exc}") from exc

    temp_path.replace(destination_path)
    return DownloadResult(
        source_url=source_url,
        destination=destination_path,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        cached=False,
    )
