"""CLITool behavior — per-OS command variants, requirements, platform derivation."""
from __future__ import annotations

import asyncio

from lesysbot.mcp import cli_tool
from lesysbot.mcp.cli_tool import CLITool


def run(coro):
    return asyncio.run(coro)


def test_string_command_leaves_platforms_unset():
    t = CLITool(name="echo", description="e", command="echo {msg}", params={"msg": "m"})
    assert t.__tool_meta__["platforms"] is None


def test_dict_command_derives_platforms():
    t = CLITool(
        name="ping", description="p",
        command={"linux": "ping -c 3 {h}", "windows": "ping -n 3 {h}"},
        params={"h": "host"},
    )
    assert t.__tool_meta__["platforms"] == ["linux", "windows"]


def test_explicit_platforms_beat_dict_keys():
    t = CLITool(
        name="ping", description="p",
        command={"linux": "ping -c 3 {h}"}, params={"h": "host"},
        platforms=["linux", "macos"],
    )
    assert t.__tool_meta__["platforms"] == ["linux", "macos"]


def test_dict_command_runs_current_os_variant(monkeypatch):
    monkeypatch.setattr(cli_tool, "current_os", lambda: "windows")
    t = CLITool(
        name="say", description="s",
        command={"windows": "echo win-{msg}", "linux": "echo linux-{msg}"},
        params={"msg": "m"},
    )
    assert run(t._run(msg="hi")) == "win-hi"


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
