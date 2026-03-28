from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from dblp_mcp.database import connect
from dblp_mcp.fulltext.extract import PdfArtifacts, _validate_not_presentation
from dblp_mcp.fulltext.service import (
    fetch_publication_fulltext,
    fetch_publication_fulltexts,
)
from dblp_mcp.importer import DblpImporter
from dblp_mcp.search import get_database_status, get_publication

SAMPLE_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
  <article key="journals/test/OpenAlex2024" mdate="2024-01-01">
    <author>Alice Example</author>
    <title>OpenAlex Backed Fulltext Fetching</title>
    <year>2024</year>
    <journal>Journal of Test Data</journal>
    <doi>10.1000/openalex-test</doi>
  </article>
  <article key="journals/corr/abs-2401-12345" mdate="2024-01-02">
    <author>Bob Example</author>
    <title>ArXiv Backed Fulltext Fetching</title>
    <year>2024</year>
    <journal>CoRR</journal>
    <ee>https://arxiv.org/abs/2401.12345</ee>
    <eprint>2401.12345</eprint>
  </article>
  <inproceedings key="conf/test/Unsupported2024" mdate="2024-01-03">
    <author>Carol Example</author>
    <title>Unsupported Fulltext Source</title>
    <booktitle>Proceedings of Testing</booktitle>
    <year>2024</year>
  </inproceedings>
</dblp>
"""


class FakeResponse:
    def __init__(
        self, payload: bytes, url: str, content_type: str = "application/pdf"
    ) -> None:
        self._payload = payload
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._payload
        return self._payload[:size]

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.fixture()
def database_path(tmp_path: Path) -> Path:
    xml_path = tmp_path / "dblp.xml"
    dtd_path = tmp_path / "dblp.dtd"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    dtd_path.write_text('<!ENTITY uuml "&#252;">\n', encoding="latin-1")
    DblpImporter(database_path).import_file(xml_path)
    return database_path


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = Path("/tmp/dblp_mcp_test_pdf.pdf")
    with output.open("wb") as handle:
        writer.write(handle)
    return output.read_bytes()


def test_fetch_publication_fulltext_stores_openalex_pdf(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_openalex_urlopen(request, timeout=30):
        return FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            "https://api.openalex.org/works/https://doi.org/10.1000%2Fopenalex-test",
            "application/json",
        )

    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen", fake_openalex_urlopen
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(_pdf_bytes(), request.full_url),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.extract_pdf_artifacts",
        lambda pdf_path: PdfArtifacts(
            "OpenAlex full text", "openalex full text", 1, "unsupported", []
        ),
    )

    result = fetch_publication_fulltext(database_path, "journals/test/OpenAlex2024")

    assert result["status"] == "fetched"
    assert result["fulltext"]["provider"] == "openalex_pdf"
    assert result["fulltext"]["text"] == "OpenAlex full text"
    assert result["fulltext"]["local_pdf_path"].endswith("fulltext.pdf")

    publication = get_publication(database_path, "journals/test/OpenAlex2024")
    assert publication is not None
    assert publication["fulltext"]["provider"] == "openalex_pdf"


def test_fetch_publication_fulltext_uses_cache(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=30: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(_pdf_bytes(), request.full_url),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.extract_pdf_artifacts",
        lambda pdf_path: PdfArtifacts(
            "Cached full text", "cached full text", 1, "unsupported", []
        ),
    )

    first = fetch_publication_fulltext(database_path, "journals/test/OpenAlex2024")
    assert first["status"] == "fetched"

    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider should not be used on cache hit")
        ),
    )

    second = fetch_publication_fulltext(database_path, "journals/test/OpenAlex2024")
    assert second["status"] == "cached"
    assert second["fulltext"]["text"] == "Cached full text"


def test_fetch_publication_fulltext_logs_unsupported(database_path: Path) -> None:
    result = fetch_publication_fulltext(database_path, "conf/test/Unsupported2024")
    assert result["status"] == "unsupported"

    connection = connect(database_path)
    try:
        row = connection.execute(
            "SELECT provider, status, error_code FROM fulltext_fetch_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()

    assert row["provider"] == "unavailable"
    assert row["status"] == "unsupported"
    assert row["error_code"] == "unsupported_source"


def test_fetch_publication_fulltexts_returns_mixed_results(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=30: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(_pdf_bytes(), request.full_url),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.extract_pdf_artifacts",
        lambda pdf_path: PdfArtifacts(
            "Bulk full text", "bulk full text", 1, "unsupported", []
        ),
    )

    result = fetch_publication_fulltexts(
        database_path,
        [
            "journals/test/OpenAlex2024",
            "journals/corr/abs-2401-12345",
            "conf/test/Unsupported2024",
            "missing/key",
        ],
    )
    assert result["summary"] == {
        "requested": 4,
        "fetched": 2,
        "cached": 0,
        "unsupported": 1,
        "not_found": 0,
        "missing": 1,
        "error": 0,
    }


def test_get_database_status_reports_fulltext_counts(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=30: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(_pdf_bytes(), request.full_url),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.extract_pdf_artifacts",
        lambda pdf_path: PdfArtifacts(
            "Status full text", "status full text", 1, "unsupported", []
        ),
    )

    fetch_publication_fulltext(database_path, "journals/test/OpenAlex2024")
    status = get_database_status(database_path)
    assert status["fulltexts"] == 1
    assert status["fulltext_fetch_logs"] == 1


def test_validate_not_presentation_rejects_landscape_majority() -> None:
    class Box:
        def __init__(self, width: float, height: float) -> None:
            self.width = width
            self.height = height

    class Page:
        def __init__(self, width: float, height: float) -> None:
            self.mediabox = Box(width, height)

    class Reader:
        def __init__(self) -> None:
            self.pages = [Page(1600, 900), Page(1600, 900), Page(595, 842)]

    with pytest.raises(ValueError, match="presentation-like"):
        _validate_not_presentation(Reader())


def test_ieee_provider_builds_stamp_pdf_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dblp_mcp.fulltext.base import FulltextLookup
    from dblp_mcp.fulltext.providers.ieee import IeeePdfProvider

    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.ieee.urlopen",
        lambda request, timeout=30: FakeResponse(
            b"", "https://ieeexplore.ieee.org/document/8651517/", "text/html"
        ),
    )

    candidates = IeeePdfProvider().fetch_candidates(
        FulltextLookup(doi="10.1109/LRA.2019.2901656")
    )

    assert len(candidates) == 1
    assert candidates[0].provider == "ieee_pdf"
    assert candidates[0].pdf_url.endswith("arnumber=8651517")
    assert candidates[0].request_headers is not None
    assert candidates[0].request_headers["Referer"] == "https://ieeexplore.ieee.org/"


def test_acm_provider_builds_direct_pdf_candidate() -> None:
    from dblp_mcp.fulltext.base import FulltextLookup
    from dblp_mcp.fulltext.providers.acm import AcmPdfProvider

    candidates = AcmPdfProvider().fetch_candidates(
        FulltextLookup(doi="10.1145/3583740.3626623")
    )

    assert len(candidates) == 1
    assert candidates[0].provider == "acm_pdf"
    assert (
        candidates[0].pdf_url
        == "https://dl.acm.org/doi/pdf/10.1145/3583740.3626623?download=true"
    )
    assert candidates[0].request_headers is not None
    assert (
        candidates[0].request_headers["Referer"]
        == "https://dl.acm.org/doi/10.1145/3583740.3626623"
    )


def test_fetch_publication_fulltext_returns_relative_pdf_path(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=60: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(_pdf_bytes(), request.full_url),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.extract_pdf_artifacts",
        lambda pdf_path: PdfArtifacts(
            "Relative path text", "relative path text", 1, "unsupported", []
        ),
    )

    result = fetch_publication_fulltext(
        database_path, "journals/test/OpenAlex2024", refresh=True
    )

    assert result["fulltext"]["local_pdf_path"].startswith("fulltext/")
    assert not result["fulltext"]["local_pdf_path"].startswith("/")


def test_fetch_publication_fulltext_respects_pdf_size_limit(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=60: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(
            b"%PDF-1.4" + b"x" * 32, request.full_url
        ),
    )
    monkeypatch.setattr("dblp_mcp.fulltext.service.MAX_FULLTEXT_PDF_BYTES", 8)

    result = fetch_publication_fulltext(
        database_path, "journals/test/OpenAlex2024", refresh=True
    )

    assert result["status"] == "not_found"


def test_fetch_publication_fulltext_handles_network_disabled(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.ensure_network_enabled",
        lambda: (_ for _ in ()).throw(RuntimeError("network disabled")),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("urlopen should not be called")
        ),
    )

    result = fetch_publication_fulltext(
        database_path, "journals/test/OpenAlex2024", refresh=True
    )

    assert result["status"] == "not_found"


def test_fetch_publication_fulltext_rejects_html_payloads(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.fulltext.providers.openalex.urlopen",
        lambda request, timeout=60: FakeResponse(
            json.dumps(
                {
                    "locations": [
                        {
                            "pdf_url": "https://dl.acm.org/doi/pdf/10.1000/openalex-test?download=true",
                            "landing_page_url": "https://doi.org/10.1000/openalex-test",
                        }
                    ]
                }
            ).encode("utf-8"),
            request.full_url,
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "dblp_mcp.fulltext.service.urlopen",
        lambda request, timeout=60: FakeResponse(
            b"<!DOCTYPE html><html></html>", request.full_url, "text/html"
        ),
    )

    result = fetch_publication_fulltext(
        database_path, "journals/test/OpenAlex2024", refresh=True
    )

    assert result["status"] == "not_found"
