from __future__ import annotations

import pytest

from lesysbot.mcp.decorators import tool


def test_schema_from_type_hints() -> None:
    @tool
    async def f(a: str, b: int, c: float, d: bool, e: list, g: dict) -> str:
        return "ok"

    schema = f.__tool_meta__["parameters"]
    props = schema["properties"]
    assert props["a"]["type"] == "string"
    assert props["b"]["type"] == "integer"
    assert props["c"]["type"] == "number"
    assert props["d"]["type"] == "boolean"
    assert props["e"]["type"] == "array"
    assert props["g"]["type"] == "object"


def test_optional_param_not_required() -> None:
    @tool
    async def f(required: str, optional: str = "x") -> str:
        return "ok"

    assert f.__tool_meta__["parameters"]["required"] == ["required"]


def test_unknown_type_defaults_to_string() -> None:
    @tool
    async def f(x: complex) -> str:  # complex isn't in the type map
        return "ok"

    assert f.__tool_meta__["parameters"]["properties"]["x"]["type"] == "string"


def test_description_and_name_defaults() -> None:
    @tool
    async def my_tool(x: str) -> str:
        """Docstring used as description."""
        return x

    meta = my_tool.__tool_meta__
    assert meta["name"] == "my_tool"
    assert meta["description"] == "Docstring used as description."


def test_custom_name_and_confirm() -> None:
    @tool(name="renamed", confirm="sure?")
    async def f(x: str) -> str:
        return x

    assert f.__tool_meta__["name"] == "renamed"
    assert f.__tool_meta__["confirm"] == "sure?"


@pytest.mark.asyncio
async def test_sync_function_wrapped_async() -> None:
    @tool
    def add(a: int, b: int) -> int:
        return a + b

    # wrapper is always async, even for sync source functions
    assert await add.__tool_meta__["fn"](a=1, b=2) == 3
