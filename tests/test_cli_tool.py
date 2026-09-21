"""CLITool behavior — per-OS command variants, requirements, platform derivation."""
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


def test_dict_command_missing_os_explains(monkeypatch):
    monkeypatch.setattr(cli_tool, "current_os", lambda: "macos")
    t = CLITool(name="say", description="s", command={"windows": "echo {msg}"},
                params={"msg": "m"})
    out = run(t._run(msg="hi"))
    assert "no command for this OS" in out
    assert "macos" in out


def _traceroute() -> CLITool:
    """The case OS-keyed requires exists for: one tool, two binary names."""
    return CLITool(
        name="traceroute", description="t",
        command={"linux": "traceroute {h}", "windows": "tracert {h}"},
        params={"h": "host"},
        requires={"linux": ["traceroute"], "windows": ["tracert"]},
    )


def test_flat_requires_is_unchanged():
    t = CLITool(name="ping", description="p", command="ping {h}",
                params={"h": "host"}, requires=["ping"])
    assert t.__tool_meta__["requires"] == ["ping"]


def test_requires_defaults_to_none():
    t = CLITool(name="ping", description="p", command="ping {h}", params={"h": "host"})
    assert t.__tool_meta__["requires"] is None


def test_dict_requires_resolves_for_current_os(monkeypatch):
    monkeypatch.setattr(cli_tool, "current_os", lambda: "windows")
    assert _traceroute().__tool_meta__["requires"] == ["tracert"]

    monkeypatch.setattr(cli_tool, "current_os", lambda: "linux")
    assert _traceroute().__tool_meta__["requires"] == ["traceroute"]


def test_dict_requires_on_unlisted_os_requires_nothing(monkeypatch):
    """`platforms` gates the OS; a missing requires key is not a requirement."""
    monkeypatch.setattr(cli_tool, "current_os", lambda: "macos")
    assert _traceroute().__tool_meta__["requires"] is None


def test_dict_requires_does_not_disturb_platform_derivation(monkeypatch):
    monkeypatch.setattr(cli_tool, "current_os", lambda: "linux")
    assert _traceroute().__tool_meta__["platforms"] == ["linux", "windows"]
