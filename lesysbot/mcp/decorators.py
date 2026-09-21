from __future__ import annotations

import asyncio
import functools
import inspect
import typing
from typing import Any, Callable

from lesysbot.mcp._legacy import note_platforms

# Python type hint → JSON schema type. Anything unmapped falls back to "string".
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def tool(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    confirm: bool | str = False,
    requires: list[str] | None = None,
    platforms: list[str] | None = None,   # legacy, ignored — see mcp/_legacy.py
) -> Any:
    """Decorator to register a Python function as an MCP tool.

    Usage:
        @tool
        async def my_tool(x: str) -> str: ...

        @tool(description="Does something useful")
        def my_tool(x: str) -> str: ...

    Requirement gating:
        requires — external executables that must be on PATH (checked with
                   shutil.which), e.g. ["nvidia-smi"]. None means no requirement.
        With a missing executable the tool is still registered but calling it
        returns a one-line explanation instead of running.

    ``platforms`` is accepted and ignored: LeSysBot is Linux-only, so there is
    no OS to choose between. It exists so tool packages written against the
    older API keep loading; see :mod:`lesysbot.mcp._legacy`.
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        note_platforms(tool_name, platforms)
        tool_description = description or (inspect.getdoc(func) or "")

        schema = _build_schema(func)

        @functools.wraps(func)
        async def wrapper(**kwargs: Any) -> Any:
            if asyncio.iscoroutinefunction(func):
                return await func(**kwargs)
            return func(**kwargs)

        wrapper.__tool_meta__ = {  # type: ignore[attr-defined]
            "name": tool_name,
            "description": tool_description,
            "parameters": schema,
            "fn": wrapper,
            "confirm": confirm,
            "requires": requires,
        }
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def _build_schema(func: Callable) -> dict[str, Any]:
    """Build a JSON schema for function parameters using type hints."""
    sig = inspect.signature(func)
    # get_type_hints resolves string annotations (PEP 563 /
    # `from __future__ import annotations`) back to real types; reading
    # __annotations__ directly would leave them as strings and mis-type every
    # parameter as "string".
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = getattr(func, "__annotations__", {})

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        py_type = hints.get(param_name, str)
        json_type = _TYPE_MAP.get(py_type, "string")

        properties[param_name] = {"type": json_type}

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
