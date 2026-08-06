"""Tool source mapping + removal (`lesysbot remove`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lesysbot.mcp.registry import ToolRegistry

PKG_TOOL = '''
from lesysbot.mcp import tool

@tool(description="alpha")
async def alpha() -> str:
    return "a"

@tool(description="beta")
async def beta() -> str:
    return "b"
'''

LOOSE_TOOL = '''
from lesysbot.mcp import tool

@tool(description="gamma")
async def gamma() -> str:
    return "g"
'''


@pytest.fixture
def tools_dir(tmp_path):
    d = tmp_path / "tools"
    (d / "pkga").mkdir(parents=True)
    (d / "pkga" / "tool.py").write_text(PKG_TOOL)
    (d / "loose.py").write_text(LOOSE_TOOL)
    return d


@pytest.fixture
def registry(tools_dir, tmp_path):
    r = ToolRegistry()
    r.set_state_path(tmp_path / "tool_state.json")
    r.load_directory(tools_dir)
    return r


def test_tool_source_package(registry, tools_dir):
    info = registry.tool_source("alpha")
    assert info["kind"] == "package"
    assert info["unit"] == "pkga"
    assert Path(info["path"]) == (tools_dir / "pkga").resolve()
    assert info["tools"] == ["alpha", "beta"]


def test_tool_source_loose_file(registry, tools_dir):
    info = registry.tool_source("gamma")
    assert info["kind"] == "file"
    assert Path(info["path"]) == (tools_dir / "loose.py").resolve()
    assert info["tools"] == ["gamma"]


def test_tool_status_includes_source(registry):
    rows = {r["name"]: r for r in registry.tool_status()}
    assert rows["alpha"]["source"]["unit"] == "pkga"
    assert rows["gamma"]["source"]["kind"] == "file"


def test_remove_package_deletes_folder_and_siblings(registry, tools_dir, tmp_path):
    registry.disable("beta")
    info = registry.remove_tool("alpha")
    assert info["tools"] == ["alpha", "beta"]
    assert not (tools_dir / "pkga").exists()
    assert "alpha" not in registry.names and "beta" not in registry.names
    assert "gamma" in registry.names
    # the disabled sibling was purged from persisted state too
    state = json.loads((tmp_path / "tool_state.json").read_text())
    assert state["disabled"] == []


def test_remove_loose_file(registry, tools_dir):
    registry.remove_tool("gamma")
    assert not (tools_dir / "loose.py").exists()
    assert "gamma" not in registry.names
    assert (tools_dir / "pkga").exists()


def test_remove_unknown_tool_raises(registry):
    with pytest.raises(KeyError):
        registry.remove_tool("nope")


def test_programmatic_tool_has_no_source_and_refuses_removal(registry):
    registry.register({"name": "prog", "description": "", "parameters": {}, "fn": None})
    assert registry.tool_source("prog") is None
    with pytest.raises(ValueError):
        registry.remove_tool("prog")
