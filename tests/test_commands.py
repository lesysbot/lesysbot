"""Tests for the shared slash-command specs (lesysbot/messaging/commands.py) —
what gets offered to a platform's command menu, and the text form native
commands are routed back through.
"""
from __future__ import annotations

from lesysbot.mcp import CLITool, tool
from lesysbot.mcp.registry import ToolRegistry
from lesysbot.messaging import commands


def _registry() -> ToolRegistry:
    reg = ToolRegistry()

    @tool(description="Check free disk space")
    def disk_usage(path: str, depth: int = 1) -> str:
        return path

    @tool(description="Measure download speed")
    def speedtest(size_mb: float = 10.0, verbose: bool = False) -> str:
        return "fast"

    reg.register_callable(disk_usage)
    reg.register_callable(speedtest)
    return reg


def _named(specs, name):
    return next(s for s in specs if s.name == name)


# ── which commands are offered ─────────────────────────────────────────────


def test_builtins_come_first_and_help_leads():
    specs = commands.all_commands(_registry())
    assert [s.name for s in specs[:3]] == ["help", "clear", "history"]


def test_tool_params_carry_type_and_required():
    spec = _named(commands.tool_commands(_registry()), "disk_usage")
    assert spec.description == "Check free disk space"
    assert [(p.name, p.json_type, p.required) for p in spec.params] == [
        ("path", "string", True),
        ("depth", "integer", False),
    ]


def test_float_and_bool_params_keep_their_json_types():
    spec = _named(commands.tool_commands(_registry()), "speedtest")
    assert [(p.name, p.json_type) for p in spec.params] == [
        ("size_mb", "number"),
        ("verbose", "boolean"),
    ]


def test_clitool_param_descriptions_are_used():
    reg = ToolRegistry()
    reg.register_callable(
        CLITool(name="ping", description="Ping a host",
                command="ping -c 1 {host}", params={"host": "Host to ping"})
    )
    spec = _named(commands.tool_commands(reg), "ping")
    assert spec.params[0].description == "Host to ping"


def test_param_description_falls_back_to_the_name():
    # `@tool` records no per-parameter text, but Discord requires a description.
    spec = _named(commands.tool_commands(_registry()), "disk_usage")
    assert spec.params[0].description == "path"


def test_disabled_tools_are_not_offered():
    reg = _registry()
    reg.disable("speedtest")
    names = [s.name for s in commands.tool_commands(reg)]
    assert "disk_usage" in names
    assert "speedtest" not in names


def test_tools_unavailable_on_this_host_are_not_offered():
    reg = ToolRegistry()
    reg.register_callable(
        CLITool(name="winonly", description="Windows only",
                command={"windows": "ver"}, params={})
    )
    # Registered but gated off every non-Windows host, so it must not be offered
    # as a command whose only possible reply is "unavailable here".
    offered = [s.name for s in commands.tool_commands(reg)]
    import sys
    assert ("winonly" in offered) == sys.platform.startswith("win")


def test_illegal_command_names_are_skipped_not_renamed(caplog):
    reg = ToolRegistry()
    reg.register_callable(
        CLITool(name="cpu-temp", description="Hyphens are illegal on Telegram",
                command="true", params={})
    )
    with caplog.at_level("WARNING"):
        assert commands.tool_commands(reg) == []
    assert "cpu-temp" in caplog.text


def test_descriptions_are_clamped_to_the_platform_limit():
    reg = ToolRegistry()
    reg.register_callable(
        CLITool(name="chatty", description="D" * 400, command="true", params={})
    )
    spec = _named(commands.tool_commands(reg), "chatty")
    assert len(spec.description) == commands.MAX_DESCRIPTION_LEN
    assert spec.description.endswith("…")


def test_blank_description_gets_a_placeholder():
    # Both platforms reject an empty description; a tool without one is legal.
    reg = ToolRegistry()
    reg.register_callable(CLITool(name="bare", description="", command="true", params={}))
    assert _named(commands.tool_commands(reg), "bare").description


def test_command_count_is_capped(caplog):
    reg = ToolRegistry()
    for i in range(commands.MAX_COMMANDS + 20):
        reg.register_callable(
            CLITool(name=f"t{i}", description="x", command="true", params={})
        )
    with caplog.at_level("WARNING"):
        specs = commands.all_commands(reg)
    assert len(specs) == commands.MAX_COMMANDS
    assert "platform limit" in caplog.text


# ── the text form native commands are routed through ───────────────────────


def test_to_slash_text_renders_named_arguments():
    assert commands.to_slash_text("disk_usage", {"path": "/"}) == "/disk_usage path=/"


def test_to_slash_text_quotes_values_with_spaces():
    text = commands.to_slash_text("open", {"path": "/my dir/x"})
    assert text == "/open path='/my dir/x'"
    # …and survives the shlex round trip the agent does.
    import shlex
    assert shlex.split(text[1:]) == ["open", "path=/my dir/x"]


def test_to_slash_text_lowercases_booleans():
    # "True" is not a value the registry's boolean coercion accepts.
    assert commands.to_slash_text("t", {"flag": True}) == "/t flag=true"
    assert commands.to_slash_text("t", {"flag": False}) == "/t flag=false"


def test_to_slash_text_drops_unset_optionals():
    # A blank Discord option arrives as None; passing it would override the
    # tool's own default with nothing.
    assert commands.to_slash_text("t", {"a": 1, "b": None}) == "/t a=1"


def test_to_slash_text_with_no_arguments():
    assert commands.to_slash_text("help", {}) == "/help"
