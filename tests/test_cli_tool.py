"""CLITool behavior — commands, requirements, and the legacy OS-keyed forms."""
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


def test_legacy_dict_command_uses_the_linux_entry():
    """An OS-keyed command from the pre-Linux-only API still runs its Linux arm."""
    t = CLITool(name="say", description="s",
                command={"linux": "echo hi-{msg}", "windows": "echo bye-{msg}"},
                params={"msg": "m"})
    assert run(t._run(msg="there")) == "hi-there"


def test_legacy_dict_command_without_linux_explains():
    """No Linux arm means there is nothing to run here — say so, don't shell out."""
    t = CLITool(name="say", description="s", command={"windows": "echo {msg}"},
                params={"msg": "m"})
    assert "no command for Linux" in run(t._run(msg="hi"))


def _traceroute() -> CLITool:
    """The case OS-keyed requires existed for: one tool, two binary names."""
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


def test_legacy_dict_requires_resolves_to_linux():
    assert _traceroute().__tool_meta__["requires"] == ["traceroute"]


def test_legacy_dict_requires_without_linux_requires_nothing():
    """A dict that never mentions Linux asks nothing of this machine."""
    t = CLITool(name="tracert", description="t", command="tracert {h}",
                params={"h": "host"}, requires={"windows": ["tracert"]})
    assert t.__tool_meta__["requires"] is None


def test_platforms_is_accepted_but_absent_from_the_meta():
    """The legacy argument must not resurrect a `platforms` key the registry
    would then have to understand."""
    t = CLITool(name="ping", description="p", command="ping {h}",
                params={"h": "host"}, platforms=["linux", "windows"])
    assert "platforms" not in t.__tool_meta__
