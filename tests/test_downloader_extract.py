from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from dblp_mcp.downloader import _validate_source_url, download_dblp_dump
from dblp_mcp.fulltext.extract import (
    _validate_not_presentation,
    extract_pdf_artifacts,
)


class FakeErrorResponse:
    def __init__(self) -> None:
        self.headers = {}

    def read(self, size: int = -1) -> bytes:
        return b""

    def close(self) -> None:
        return None


def test_validate_source_url_rejects_wrong_host() -> None:
    with pytest.raises(ValueError, match="dblp.org"):
        _validate_source_url("https://example.com/xml/dblp.xml.gz")


def test_validate_source_url_rejects_wrong_path() -> None:
    with pytest.raises(ValueError, match="XML area"):
        _validate_source_url("https://dblp.org/other/dblp.xml.gz")


def test_download_removes_partial_file_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = Path("data/test-http-error/dblp.xml.gz")

    def fail(*args, **kwargs):
        raise HTTPError(
            "https://dblp.org/xml/dblp.xml.gz", 500, "boom", {}, FakeErrorResponse()
        )

    monkeypatch.setattr("dblp_mcp.downloader.urlopen", fail)

    with pytest.raises(RuntimeError, match="HTTP status 500"):
        download_dblp_dump(destination=destination, replace=True)

    assert not destination.with_suffix(".gz.part").exists()


def test_download_removes_partial_file_on_url_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = Path("data/test-url-error/dblp.xml.gz")
    monkeypatch.setattr(
        "dblp_mcp.downloader.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        download_dblp_dump(destination=destination, replace=True)

    assert not destination.with_suffix(".gz.part").exists()


def test_extract_pdf_artifacts_rejects_pdfs_with_no_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Reader:
        def __init__(self, path: str) -> None:
            self.pages = []

    monkeypatch.setattr("dblp_mcp.fulltext.extract.PdfReader", Reader)

    with pytest.raises(ValueError, match="no pages"):
        extract_pdf_artifacts(tmp_path / "empty.pdf")


def test_extract_pdf_artifacts_rejects_too_little_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Box:
        width = 595
        height = 842

    class Page:
        mediabox = Box()

        def extract_text(self) -> str:
            return "tiny"

    class Reader:
        def __init__(self, path: str) -> None:
            self.pages = [Page()]

    monkeypatch.setattr("dblp_mcp.fulltext.extract.PdfReader", Reader)

    with pytest.raises(ValueError, match="too little text"):
        extract_pdf_artifacts(tmp_path / "tiny.pdf")


def test_validate_not_presentation_allows_portrait_pages() -> None:
    class Box:
        def __init__(self, width: float, height: float) -> None:
            self.width = width
            self.height = height

    class Page:
        def __init__(self) -> None:
            self.mediabox = Box(595, 842)

    class Reader:
        def __init__(self) -> None:
            self.pages = [Page(), Page()]

    _validate_not_presentation(Reader())
