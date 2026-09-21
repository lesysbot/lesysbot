from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from lesysbot.mcp import tool
from lesysbot.mcp.registry import ToolRegistry


def _write_tools(tmp_path: Path, **files: str) -> Path:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for name, body in files.items():
        (tools_dir / name).write_text(textwrap.dedent(body))
    return tools_dir


def _write_package(tools_dir: Path, package: str, **files: str) -> Path:
    """Create a folder package `tools_dir/<package>/` with the given files."""
    pkg = tools_dir / package
    pkg.mkdir(parents=True)
    for name, body in files.items():
        (pkg / name).write_text(textwrap.dedent(body))
    return pkg


def test_tool_discovery(tmp_path: Path) -> None:
    """@tool functions and CLITool instances are discovered; `_`-files ignored."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "good.py": """
                from lesysbot.mcp import tool, CLITool

                @tool(description="echo")
                async def echo(text: str) -> str:
                    return text

                ping = CLITool(name="ping", description="p", command="echo {host}",
                               params={"host": "h"})
            """,
            "_ignored.py": """
                from lesysbot.mcp import tool

                @tool
                async def hidden() -> str:
                    return "no"
            """,
        },
    )

    registry = ToolRegistry()
    registry.load_directory(tools_dir)

    assert set(registry.names) == {"echo", "ping"}
    assert "hidden" not in registry.names


@pytest.mark.asyncio
async def test_call_tool(tmp_path: Path) -> None:
    tools_dir = _write_tools(
        tmp_path,
        **{
            "t.py": """
                from lesysbot.mcp import tool

                @tool
                async def add(a: int, b: int) -> int:
                    return a + b
            """
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert await registry.call("add", {"a": 2, "b": 3}) == "5"


@pytest.mark.asyncio
async def test_call_unknown_tool(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.load_directory(_write_tools(tmp_path))
    assert "Unknown tool" in await registry.call("nope", {})


def test_helper_import(tmp_path: Path) -> None:
    """Tool files can import sibling `_helper` modules (tools dir on sys.path)."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "_helpers.py": "VALUE = 'shared'\n",
            "uses_helper.py": """
                from _helpers import VALUE
                from lesysbot.mcp import tool

                @tool
                async def get() -> str:
                    return VALUE
            """,
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert "get" in registry.names


@pytest.mark.asyncio
async def test_helper_hot_reload(tmp_path: Path) -> None:
    """Editing a `_helper` module is picked up on reload."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "_v.py": "VERSION = 'v1'\n",
            "ver.py": """
                from _v import VERSION
                from lesysbot.mcp import tool

                @tool
                async def ver() -> str:
                    return VERSION
            """,
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert await registry.call("ver", {}) == "v1"

    helper = tools_dir / "_v.py"
    helper.write_text("VERSION = 'v2'\n")
    # Advance mtime so the import system doesn't reuse stale bytecode cached
    # from the v1 write (.pyc validity is checked at second granularity; a real
    # editor edit always lands a later mtime).
    import os
    future = helper.stat().st_mtime + 10
    os.utime(helper, (future, future))

    registry.reload(tools_dir)
    assert await registry.call("ver", {}) == "v2"


@pytest.mark.asyncio
async def test_missing_bin_stub(tmp_path: Path) -> None:
    """A tool requiring an absent executable is gated to an explaining stub."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "t.py": """
                from lesysbot.mcp import tool

                @tool(requires=["definitely-not-a-real-binary-xyz"])
                async def needs_bin() -> str:
                    return "ran"
            """
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert registry.get_tool_meta("needs_bin")["available"] is False
    result = await registry.call("needs_bin", {})
    assert "definitely-not-a-real-binary-xyz" in result


@pytest.mark.asyncio
async def test_folder_package_loads(tmp_path: Path) -> None:
    """A folder package (README + tool.py) is discovered and registered."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    _write_package(
        tools_dir,
        "greeter",
        **{
            "README.md": "---\nname: greeter\n---\n# greeter\n",
            "tool.py": """
                from lesysbot.mcp import tool

                @tool
                async def greet(name: str) -> str:
                    return f"hi {name}"
            """,
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert "greet" in registry.names
    assert await registry.call("greet", {"name": "bob"}) == "hi bob"


@pytest.mark.asyncio
async def test_package_local_helper(tmp_path: Path) -> None:
    """Two packages can each ship a `_helpers.py` without clobbering each other."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    _write_package(
        tools_dir,
        "alpha",
        **{
            "_helpers.py": "VALUE = 'alpha'\n",
            "tool.py": """
                from _helpers import VALUE
                from lesysbot.mcp import tool

                @tool
                async def a() -> str:
                    return VALUE
            """,
        },
    )
    _write_package(
        tools_dir,
        "beta",
        **{
            "_helpers.py": "VALUE = 'beta'\n",
            "tool.py": """
                from _helpers import VALUE
                from lesysbot.mcp import tool

                @tool
                async def b() -> str:
                    return VALUE
            """,
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    assert await registry.call("a", {}) == "alpha"
    assert await registry.call("b", {}) == "beta"


@pytest.mark.asyncio
async def test_disable_hides_from_schemas_and_call(tmp_path: Path) -> None:
    """A disabled tool is omitted from LLM schemas and refuses to run; enabling restores."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "t.py": """
                from lesysbot.mcp import tool

                @tool
                async def echo(text: str) -> str:
                    return text
            """
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)

    # Enabled by default.
    assert registry.is_enabled("echo")
    assert any(s["function"]["name"] == "echo" for s in registry.get_openai_schemas())
    assert await registry.call("echo", {"text": "hi"}) == "hi"

    registry.disable("echo")
    assert not registry.is_enabled("echo")
    assert not any(s["function"]["name"] == "echo" for s in registry.get_openai_schemas())
    assert "disabled" in (await registry.call("echo", {"text": "hi"})).lower()
    # Still listed in tool_status, just marked disabled.
    assert any(t["name"] == "echo" and not t["enabled"] for t in registry.tool_status())

    registry.enable("echo")
    assert await registry.call("echo", {"text": "hi"}) == "hi"


def test_state_persistence(tmp_path: Path) -> None:
    """Disabled tools persist to the state file and reload into a fresh registry."""
    tools_dir = _write_tools(
        tmp_path,
        **{
            "t.py": """
                from lesysbot.mcp import tool

                @tool
                async def a() -> str:
                    return "a"
            """
        },
    )
    state = tmp_path / "tool_state.json"

    r1 = ToolRegistry()
    r1.set_state_path(state)
    r1.load_directory(tools_dir)
    r1.disable("a")
    assert state.exists()

    r2 = ToolRegistry()
    r2.set_state_path(state)
    r2.load_state()
    r2.load_directory(tools_dir)
    assert not r2.is_enabled("a")


def test_openai_schema_shape(tmp_path: Path) -> None:
    tools_dir = _write_tools(
        tmp_path,
        **{
            "t.py": """
                from lesysbot.mcp import tool

                @tool(description="d")
                async def f(x: str) -> str:
                    return x
            """
        },
    )
    registry = ToolRegistry()
    registry.load_directory(tools_dir)
    schemas = registry.get_openai_schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "f"
    assert schemas[0]["function"]["parameters"]["required"] == ["x"]


# ── argument coercion ──────────────────────────────────────────────────────
# Arguments arrive as text from two directions that can't type them: a
# `/tool size_mb=10` slash command parsed out of a chat message, and an LLM
# quoting numbers in its tool-call JSON. call() coerces to the declared types.


def _typed_registry() -> ToolRegistry:
    registry = ToolRegistry()

    @tool(description="echo argument types")
    def probe(count: int, ratio: float, flag: bool, name: str = "dflt") -> str:
        return f"{count!r} {ratio!r} {flag!r} {name!r}"

    registry.register_callable(probe)
    return registry


async def test_string_arguments_are_coerced_to_declared_types() -> None:
    registry = _typed_registry()
    out = await registry.call("probe", {"count": "3", "ratio": "1.5", "flag": "true"})
    assert out == "3 1.5 True 'dflt'"


async def test_already_typed_arguments_pass_through() -> None:
    registry = _typed_registry()
    out = await registry.call("probe", {"count": 3, "ratio": 1.5, "flag": False})
    assert out == "3 1.5 False 'dflt'"


@pytest.mark.parametrize(
    "raw,expected",
    [("yes", True), ("y", True), ("1", True), ("on", True), ("TRUE", True),
     ("no", False), ("n", False), ("0", False), ("off", False), ("False", False)],
)
async def test_boolean_spellings(raw, expected) -> None:
    registry = _typed_registry()
    out = await registry.call("probe", {"count": "1", "ratio": "1", "flag": raw})
    assert out.split()[2] == repr(expected)


async def test_integral_float_is_accepted_for_an_int_parameter() -> None:
    # An LLM emitting 3.0 for an int parameter means 3.
    registry = _typed_registry()
    out = await registry.call("probe", {"count": "3.0", "ratio": "1", "flag": "y"})
    assert out.startswith("3 ")


@pytest.mark.parametrize(
    "args,message",
    [
        ({"count": "abc"}, "count must be a whole number"),
        ({"count": "3.5"}, "count must be a whole number"),
        ({"ratio": "wide"}, "ratio must be a number"),
        ({"flag": "maybe"}, "flag must be true or false"),
    ],
)
async def test_uncoercible_argument_reports_the_parameter(args, message) -> None:
    registry = _typed_registry()
    call_args = {"count": "1", "ratio": "1", "flag": "y", **args}
    out = await registry.call("probe", call_args)
    assert message in out
    assert out.startswith("Tool error:")


async def test_unknown_and_untyped_arguments_are_left_alone() -> None:
    registry = ToolRegistry()

    @tool(description="takes anything")
    def loose(payload: dict, extra: str = "") -> str:
        return f"{payload!r} {extra!r}"

    registry.register_callable(loose)
    # dict/list have no textual form worth guessing — passed through untouched.
    out = await registry.call("loose", {"payload": "{not json}", "extra": "x"})
    assert out == "'{not json}' 'x'"
