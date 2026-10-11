"""CLITool behavior — command interpolation and requirement metadata."""
from __future__ import annotations

import asyncio

from lesysbot.mcp.cli_tool import CLITool


def run(coro):
    return asyncio.run(coro)


def test_meta_shape():
    t = CLITool(name="echo", description="e", command="echo {msg}", params={"msg": "m"})
    meta = t.__tool_meta__
    assert meta["name"] == "echo"
    assert meta["requires"] is None
    assert meta["parameters"]["required"] == ["msg"]


def test_requires_is_carried_into_meta():
    t = CLITool(
        name="mtr", description="trace", command="mtr {h}",
        params={"h": "host"}, requires=["mtr"],
    )
    assert t.__tool_meta__["requires"] == ["mtr"]


def test_command_is_interpolated_and_run():
    t = CLITool(name="say", description="s", command="echo hi-{msg}", params={"msg": "m"})
    assert run(t._run(msg="there")) == "hi-there"


def test_missing_parameter_explains():
    t = CLITool(name="say", description="s", command="echo {msg}", params={"msg": "m"})
    assert "missing parameter" in run(t._run())


def test_flat_requires_is_unchanged():
    t = CLITool(name="ping", description="p", command="ping {h}",
                params={"h": "host"}, requires=["ping"])
    assert t.__tool_meta__["requires"] == ["ping"]


def test_requires_defaults_to_none():
    t = CLITool(name="ping", description="p", command="ping {h}", params={"h": "host"})
    assert t.__tool_meta__["requires"] is None
