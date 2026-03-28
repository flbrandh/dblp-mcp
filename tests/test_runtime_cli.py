from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from dblp_mcp.cli import main as cli_main
from dblp_mcp.runtime import main as runtime_main
from dblp_mcp.runtime import parse_args


def test_runtime_parse_args_supports_flags() -> None:
    args = parse_args(["--privileged", "--allow-implicit-data-dir"])

    assert args.privileged is True
    assert args.allow_implicit_data_dir is True


def test_runtime_main_requires_explicit_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dblp_mcp.runtime.data_dir_was_explicitly_configured", lambda: False
    )

    with pytest.raises(SystemExit, match="DBLP_MCP_DATA_DIR must be set explicitly"):
        runtime_main([])


def test_runtime_main_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    class FakeMCP:
        def run(self) -> None:
            calls.append(True)

    monkeypatch.setattr(
        "dblp_mcp.runtime.data_dir_was_explicitly_configured", lambda: True
    )
    monkeypatch.setattr("dblp_mcp.runtime.create_mcp", lambda privileged: FakeMCP())

    runtime_main(["--privileged"])

    assert calls == [True]


def test_package_main_invokes_runtime_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("dblp_mcp.runtime.main", lambda: calls.append("called"))
    monkeypatch.setattr(sys, "argv", ["dblp-mcp"])

    runpy.run_module("dblp_mcp.__main__", run_name="__main__")

    assert calls == ["called"]


def test_cli_search_command_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr(
        "dblp_mcp.cli.search_publications",
        lambda **kwargs: {
            "term_groups": kwargs["term_groups"],
            "count": 0,
            "results": [],
        },
    )
    monkeypatch.setattr("builtins.print", lambda value: lines.append(value))

    cli_main(["search", "--term-group", "test query"])

    payload = json.loads(lines[0])
    assert payload["term_groups"] == [["test", "query"]]


def test_cli_get_command_prints_null(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr("dblp_mcp.cli.get_publication", lambda *args: None)
    monkeypatch.setattr("builtins.print", lambda value: lines.append(value))

    cli_main(["get", "--dblp-key", "missing/key"])

    assert lines == ["null"]


def test_cli_download_command_serializes_dataclass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dblp_mcp.downloader import DownloadResult

    lines: list[str] = []
    monkeypatch.setattr(
        "dblp_mcp.cli.download_dblp_dump",
        lambda **kwargs: DownloadResult(
            source_url="https://dblp.org/xml/dblp.xml.gz",
            destination=tmp_path / "dblp.xml.gz",
            size_bytes=1,
            sha256="abc",
            downloaded_at="now",
            cached=True,
        ),
    )
    monkeypatch.setattr("builtins.print", lambda value: lines.append(value))

    cli_main(["download"])

    payload = json.loads(lines[0])
    assert payload["cached"] is True
