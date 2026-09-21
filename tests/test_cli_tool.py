"""CLITool behavior — command interpolation and requirement gating."""
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


# ── legacy API kept loading (see lesysbot/mcp/_legacy.py) ──────────────────


def test_legacy_platforms_is_accepted_and_ignored():
    """A package written before LeSysBot went Linux-only must still load."""
    t = CLITool(name="say", description="s", command="echo hi", params={},
                platforms=["linux", "macos"])
    assert "platforms" not in t.__tool_meta__
    assert run(t._run()) == "hi"


def test_legacy_os_keyed_command_runs_the_linux_entry():
    t = CLITool(name="say", description="s", params={"msg": "m"},
                command={"linux": "echo linux-{msg}", "windows": "echo win-{msg}"})
    assert run(t._run(msg="hi")) == "linux-hi"


def test_legacy_command_dict_without_linux_explains():
    t = CLITool(name="say", description="s", params={},
                command={"windows": "ver"})
    assert "no command for Linux" in run(t._run())
