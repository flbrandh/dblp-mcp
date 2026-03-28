from __future__ import annotations

from pathlib import Path

import pytest

from dblp_mcp.config import DEFAULT_DATA_DIR, resolve_data_path
from dblp_mcp.server import create_mcp


def _tool_names(mcp) -> set[str]:
    return set(mcp._tool_manager._tools.keys())


def test_unprivileged_server_hides_download_and_build_tools() -> None:
    tool_names = _tool_names(create_mcp(privileged=False))

    assert 'download_dblp_dump' not in tool_names
    assert 'build_dblp_sqlite' not in tool_names
    assert 'search_publications' in tool_names
    assert 'get_dblp_status' in tool_names


def test_privileged_server_exposes_download_and_build_tools() -> None:
    tool_names = _tool_names(create_mcp(privileged=True))

    assert 'download_dblp_dump' in tool_names
    assert 'build_dblp_sqlite' in tool_names
    assert 'search_publications' in tool_names
    assert 'get_dblp_status' in tool_names


def test_resolve_data_path_rejects_paths_outside_data_dir() -> None:
    with pytest.raises(ValueError, match='DBLP_MCP_DATA_DIR'):
        resolve_data_path(DEFAULT_DATA_DIR.parent / 'outside.sqlite')


def test_resolve_data_path_places_relative_paths_under_data_dir() -> None:
    resolved = resolve_data_path('nested/test.sqlite')

    assert resolved == DEFAULT_DATA_DIR / 'nested' / 'test.sqlite'
