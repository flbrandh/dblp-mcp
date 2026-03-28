from __future__ import annotations

import json
from pathlib import Path

import pytest

from dblp_mcp.abstracts.service import (
    fetch_publication_abstract,
    fetch_publication_abstracts,
)
from dblp_mcp.database import connect
from dblp_mcp.importer import DblpImporter
from dblp_mcp.search import get_database_status, get_publication

SAMPLE_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
  <article key="journals/test/OpenAlex2024" mdate="2024-01-01">
    <author>Alice Example</author>
    <title>OpenAlex Backed Abstract Fetching</title>
    <year>2024</year>
    <journal>Journal of Test Data</journal>
    <doi>10.1000/openalex-test</doi>
  </article>
  <article key="journals/corr/abs-2401-12345" mdate="2024-01-02">
    <author>Bob Example</author>
    <title>ArXiv Backed Abstract Fetching</title>
    <year>2024</year>
    <journal>CoRR</journal>
    <ee>https://arxiv.org/abs/2401.12345</ee>
    <eprint>2401.12345</eprint>
  </article>
  <inproceedings key="conf/test/Unsupported2024" mdate="2024-01-03">
    <author>Carol Example</author>
    <title>Unsupported Abstract Source</title>
    <booktitle>Proceedings of Testing</booktitle>
    <year>2024</year>
  </inproceedings>
</dblp>
"""


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

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


def test_fetch_publication_abstract_stores_openalex_abstract(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout=30):
        assert request.full_url.endswith("10.1000%2Fopenalex-test")
        payload = json.dumps(
            {
                "abstract_inverted_index": {
                    "OpenAlex": [0],
                    "abstract": [1],
                    "content": [2],
                }
            }
        ).encode("utf-8")
        return FakeResponse(payload)

    monkeypatch.setattr("dblp_mcp.abstracts.providers.openalex.urlopen", fake_urlopen)

    result = fetch_publication_abstract(database_path, "journals/test/OpenAlex2024")

    assert result["status"] == "fetched"
    assert result["abstract"]["provider"] == "openalex"
    assert result["abstract"]["text"] == "OpenAlex abstract content"

    publication = get_publication(database_path, "journals/test/OpenAlex2024")
    assert publication is not None
    assert publication["abstract"]["text"] == "OpenAlex abstract content"


def test_fetch_publication_abstract_stores_arxiv_abstract(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout=30):
        assert request.full_url.endswith("2401.12345")
        return FakeResponse(b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <entry>
    <summary>
      ArXiv abstract content
    </summary>
  </entry>
</feed>
""")

    monkeypatch.setattr("dblp_mcp.abstracts.providers.arxiv.urlopen", fake_urlopen)

    result = fetch_publication_abstract(database_path, "journals/corr/abs-2401-12345")

    assert result["status"] == "fetched"
    assert result["abstract"]["provider"] == "arxiv"
    assert result["abstract"]["text"] == "ArXiv abstract content"


def test_fetch_publication_abstract_uses_cached_abstract(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.abstracts.providers.openalex.urlopen",
        lambda request, timeout=30: FakeResponse(
            json.dumps(
                {
                    "abstract_inverted_index": {
                        "Cached": [0],
                        "abstract": [1],
                    }
                }
            ).encode("utf-8")
        ),
    )

    first_result = fetch_publication_abstract(
        database_path, "journals/test/OpenAlex2024"
    )
    assert first_result["status"] == "fetched"

    def fail_urlopen(request, timeout=30):
        raise AssertionError("network should not be used on cache hits")

    monkeypatch.setattr("dblp_mcp.abstracts.providers.openalex.urlopen", fail_urlopen)

    second_result = fetch_publication_abstract(
        database_path, "journals/test/OpenAlex2024"
    )

    assert second_result["status"] == "cached"
    assert second_result["abstract"]["text"] == "Cached abstract"


def test_fetch_publication_abstract_logs_unsupported_sources(
    database_path: Path,
) -> None:
    result = fetch_publication_abstract(database_path, "conf/test/Unsupported2024")

    assert result == {
        "dblp_key": "conf/test/Unsupported2024",
        "refresh": False,
        "status": "unsupported",
        "abstract": None,
    }

    connection = connect(database_path)
    try:
        row = connection.execute(
            "SELECT provider, status, error_code FROM abstract_fetch_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row["provider"] == "unavailable"
    assert row["status"] == "unsupported"
    assert row["error_code"] == "unsupported_source"


def test_fetch_publication_abstract_raises_for_missing_publication(
    database_path: Path,
) -> None:
    with pytest.raises(LookupError, match="publication not found"):
        fetch_publication_abstract(database_path, "missing/key")


def test_get_database_status_reports_abstract_counts(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.abstracts.providers.openalex.urlopen",
        lambda request, timeout=30: FakeResponse(
            json.dumps(
                {
                    "abstract_inverted_index": {
                        "Status": [0],
                        "abstract": [1],
                    }
                }
            ).encode("utf-8")
        ),
    )

    fetch_publication_abstract(database_path, "journals/test/OpenAlex2024")
    fetch_publication_abstract(database_path, "conf/test/Unsupported2024")

    status = get_database_status(database_path)

    assert status["abstracts"] == 1
    assert status["abstract_fetch_logs"] == 2


def test_fetch_publication_abstracts_returns_mixed_results(
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openalex(request, timeout=30):
        return FakeResponse(
            json.dumps(
                {
                    "abstract_inverted_index": {
                        "Bulk": [0],
                        "OpenAlex": [1],
                    }
                }
            ).encode("utf-8")
        )

    def fake_arxiv(request, timeout=30):
        return FakeResponse(b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <entry><summary>Bulk ArXiv</summary></entry>
</feed>
""")

    monkeypatch.setattr("dblp_mcp.abstracts.providers.openalex.urlopen", fake_openalex)
    monkeypatch.setattr("dblp_mcp.abstracts.providers.arxiv.urlopen", fake_arxiv)

    result = fetch_publication_abstracts(
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
    assert [item["status"] for item in result["results"]] == [
        "fetched",
        "fetched",
        "unsupported",
        "missing",
    ]


def test_fetch_publication_abstracts_rejects_empty_lists(database_path: Path) -> None:
    with pytest.raises(ValueError, match="dblp_keys must not be empty"):
        fetch_publication_abstracts(database_path, [])


def test_fetch_publication_abstract_handles_network_disabled(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.abstracts.providers.openalex.ensure_network_enabled",
        lambda: (_ for _ in ()).throw(RuntimeError("network disabled")),
    )
    monkeypatch.setattr(
        "dblp_mcp.abstracts.providers.openalex.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("urlopen should not be called")
        ),
    )

    result = fetch_publication_abstract(database_path, "journals/test/OpenAlex2024")

    assert result["status"] == "not_found"


def test_fetch_publication_abstracts_classifies_provider_errors(
    database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.abstracts.providers.openalex.ensure_network_enabled",
        lambda: (_ for _ in ()).throw(RuntimeError("network disabled")),
    )

    result = fetch_publication_abstracts(database_path, ["journals/test/OpenAlex2024"])

    assert result["summary"]["not_found"] == 1
    assert result["results"][0]["status"] == "not_found"
