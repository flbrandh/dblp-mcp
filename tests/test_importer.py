from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from dblp_mcp.config import DEFAULT_DATA_DIR
from dblp_mcp.downloader import download_dblp_dump
from dblp_mcp.importer import DblpImporter
from dblp_mcp.search import get_database_status, get_publication, search_publications

SAMPLE_XML = """<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>
<dblp>
  <article key=\"journals/test/Example2024\" mdate=\"2024-01-01\">
    <author>Alice Example</author>
    <author>Bob Example</author>
    <title>Streaming XML for Searchable Bibliographies</title>
    <pages>1-10</pages>
    <year>2024</year>
    <volume>42</volume>
    <journal>Journal of Test Data</journal>
    <ee>https://doi.org/10.1000/example</ee>
    <doi>10.1000/example</doi>
  </article>
  <inproceedings key=\"conf/test/Builder2023\" mdate=\"2023-02-02\">
    <author>Carol Builder</author>
    <editor>Dan Editor</editor>
    <title>Building an Offline DBLP Index</title>
    <booktitle>Proceedings of the Example Conference</booktitle>
    <year>2023</year>
    <crossref>conf/test/2023</crossref>
    <url>db/conf/test/test2023.html#Builder2023</url>
  </inproceedings>
</dblp>
"""

SAMPLE_XML_WITH_DTD_ENTITY = """<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE dblp SYSTEM "dblp.dtd">
<dblp>
  <article key="journals/test/Entity2024" mdate="2024-01-01">
    <author>J&uuml;rgen Example</author>
    <title>Entity Handling for DBLP</title>
    <year>2024</year>
    <journal>Journal of Test Data</journal>
  </article>
</dblp>
"""


def _write_local_dtd(tmp_path: Path) -> None:
    (tmp_path / "dblp.dtd").write_text('<!ENTITY uuml "&#252;">\n', encoding="latin-1")


def test_import_file_builds_searchable_database(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)

    importer = DblpImporter(database_path)
    result = importer.import_file(xml_path)

    assert result["stats"]["publications"] == 2
    assert result["stats"]["contributors"] == 4

    search_result = search_publications(database_path, "streaming bibliographies")
    assert search_result["count"] == 1
    assert search_result["results"][0]["dblp_key"] == "journals/test/Example2024"
    assert search_result["results"][0]["contributors"][0]["name"] == "Alice Example"


def test_get_publication_returns_normalized_related_data(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)

    importer = DblpImporter(database_path)
    importer.import_file(xml_path)

    publication = get_publication(database_path, "conf/test/Builder2023")

    assert publication is not None
    assert publication["record_type"] == "inproceedings"
    assert publication["venues"][0]["name"] == "Proceedings of the Example Conference"
    assert publication["contributors"][0]["role"] == "author"
    assert publication["contributors"][1]["role"] == "editor"


def test_import_file_supports_gzip_input(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml.gz"
    database_path = tmp_path / "dblp.sqlite"
    _write_local_dtd(tmp_path)
    with gzip.open(xml_path, "wt", encoding="utf-8") as handle:
        handle.write(SAMPLE_XML)

    importer = DblpImporter(database_path)
    result = importer.import_file(xml_path)

    assert result["stats"]["publications"] == 2
    search_result = search_publications(database_path, "offline index")
    assert search_result["count"] == 1


def test_import_file_rejects_unsafe_append_to_existing_database(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)

    importer = DblpImporter(database_path)
    importer.import_file(xml_path)

    with pytest.raises(ValueError, match="append imports are not supported"):
        importer.import_file(xml_path, replace=False)


def test_importer_rejects_non_positive_batch_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="batch_size must be at least 1"):
        DblpImporter(tmp_path / "dblp.sqlite", batch_size=0)


def test_download_requires_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source_url must use https"):
        download_dblp_dump(
            destination=tmp_path / "dblp.xml.gz",
            source_url="http://dblp.org/xml/dblp.xml.gz",
        )


def test_download_uses_cached_file_when_destination_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = DEFAULT_DATA_DIR / "test-download-cache" / "dblp.xml.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = b"cached dblp dump"
    destination.write_bytes(payload)

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not be called when the dump already exists")

    monkeypatch.setattr("dblp_mcp.downloader.urlopen", fail_urlopen)

    result = download_dblp_dump(destination=destination)

    assert result.cached is True
    assert result.destination == destination
    assert result.size_bytes == len(payload)
    assert destination.read_bytes() == payload


def test_import_file_supports_dblp_dtd_entities(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    dtd_path = tmp_path / "dblp.dtd"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML_WITH_DTD_ENTITY, encoding="latin-1")
    dtd_path.write_text('<!ENTITY uuml "&#252;">\n', encoding="latin-1")

    importer = DblpImporter(database_path)
    importer.import_file(xml_path)

    publication = get_publication(database_path, "journals/test/Entity2024")
    assert publication is not None
    assert publication["contributors"][0]["name"] == "Jürgen Example"


def test_import_file_ignores_duplicate_identifiers(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    _write_local_dtd(tmp_path)
    xml_path.write_text(
        """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
  <article key="journals/test/Duplicate2024" mdate="2024-01-01">
    <author>Alice Example</author>
    <title>Duplicate Identifier Handling</title>
    <year>2024</year>
    <journal>Journal of Test Data</journal>
    <ee>https://doi.org/10.1000/example</ee>
    <ee>https://doi.org/10.1000/example</ee>
  </article>
</dblp>
""",
        encoding="latin-1",
    )

    importer = DblpImporter(database_path)
    result = importer.import_file(xml_path)

    publication = get_publication(database_path, "journals/test/Duplicate2024")
    assert result["stats"]["identifiers"] == 1
    assert publication is not None
    assert publication["identifiers"] == [{"kind": "ee", "value": "https://doi.org/10.1000/example"}]


def test_get_database_status_reports_imported_content(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)

    importer = DblpImporter(database_path)
    importer.import_file(xml_path)

    status = get_database_status(database_path)

    assert status["exists"] is True
    assert status["publications"] == 2
    assert status["contributors"] == 4
    assert status["abstracts"] == 0
    assert status["abstract_fetch_logs"] == 0
    assert status["import_runs"][0]["status"] == "completed"


def test_get_database_status_handles_missing_database(tmp_path: Path) -> None:
    status = get_database_status(tmp_path / "missing.sqlite")

    assert status["exists"] is False
    assert status["publications"] == 0
    assert status["contributors"] == 0
    assert status["abstracts"] == 0
    assert status["abstract_fetch_logs"] == 0


def test_search_publications_infers_year_and_prioritizes_papers(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    _write_local_dtd(tmp_path)
    xml_path.write_text(
        """<?xml version="1.0" encoding="ISO-8859-1"?>
<dblp>
  <proceedings key="conf/sigcomm/2024" mdate="2024-01-01">
    <title>Proceedings of the ACM SIGCOMM 2024 Conference</title>
    <year>2024</year>
    <booktitle>ACM SIGCOMM 2024 Conference</booktitle>
  </proceedings>
  <inproceedings key="conf/sigcomm/Paper2024" mdate="2024-01-02">
    <author>Alice Example</author>
    <title>Congestion Control with Helpful Signals</title>
    <booktitle>ACM SIGCOMM Conference</booktitle>
    <year>2024</year>
  </inproceedings>
</dblp>
""",
        encoding="utf-8",
    )

    importer = DblpImporter(database_path)
    importer.import_file(xml_path)

    result = search_publications(database_path, "sigcomm 2024", limit=5)

    assert result["count"] >= 2
    assert result["results"][0]["dblp_key"] == "conf/sigcomm/Paper2024"
    assert any(item["dblp_key"] == "conf/sigcomm/2024" for item in result["results"])


def test_search_publications_rejects_blank_query(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)
    DblpImporter(database_path).import_file(xml_path)

    with pytest.raises(ValueError, match="query must not be empty"):
        search_publications(database_path, "   ")


def test_search_publications_rejects_invalid_limits(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)
    DblpImporter(database_path).import_file(xml_path)

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        search_publications(database_path, "streaming", limit=0)
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        search_publications(database_path, "streaming", limit=101)


def test_search_publications_supports_year_only_queries(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)
    DblpImporter(database_path).import_file(xml_path)

    result = search_publications(database_path, "2024", limit=10)

    assert result["count"] == 1
    assert result["results"][0]["dblp_key"] == "journals/test/Example2024"


def test_search_publications_combines_structured_filters(tmp_path: Path) -> None:
    xml_path = tmp_path / "dblp.xml"
    database_path = tmp_path / "dblp.sqlite"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    _write_local_dtd(tmp_path)
    DblpImporter(database_path).import_file(xml_path)

    result = search_publications(
        database_path,
        "offline index",
        contributor="carol",
        venue="example conference",
        record_types=["inproceedings"],
    )

    assert result["count"] == 1
    assert result["results"][0]["dblp_key"] == "conf/test/Builder2023"


def test_download_respects_disabled_network_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = DEFAULT_DATA_DIR / 'test-download-disabled' / 'dblp.xml.gz'
    destination.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr('dblp_mcp.downloader.ensure_network_enabled', lambda: (_ for _ in ()).throw(RuntimeError('network disabled')))

    with pytest.raises(RuntimeError, match='network disabled'):
        download_dblp_dump(destination=destination, replace=True)
