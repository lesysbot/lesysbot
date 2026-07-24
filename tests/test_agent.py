from __future__ import annotations

from pathlib import Path

from lesysbot.core.agent import _EMPTY_REPLY_FALLBACK, Agent, _parse_args, _usage
from lesysbot.core.config import Settings
from lesysbot.core.types import ConversationHistory, Message, Role, ToolCall
from lesysbot.mcp import tool


def test_parse_args_positional() -> None:
    assert _parse_args(["a", "b"], ["x", "y"]) == {"x": "a", "y": "b"}


def test_parse_args_named() -> None:
    assert _parse_args(["x=a", "y=b"], ["x", "y"]) == {"x": "a", "y": "b"}


def test_parse_args_named_with_equals_in_value() -> None:
    # only the first `=` splits key/value
    assert _parse_args(["url=http://x?a=1"], ["url"]) == {"url": "http://x?a=1"}


def test_usage_lists_missing_params() -> None:
    info = {
        "name": "disk_usage",
        "description": "Check disk space",
        "param_names": ["path"],
        "required": ["path"],
    }
    text = _usage(info, ["path"])
    assert "Missing required parameter(s): path" in text
    assert "/disk_usage <path>" in text


def test_history_trims_but_keeps_system() -> None:
    history = ConversationHistory(max_size=3)
    history.add(Message(role=Role.SYSTEM, content="sys"))
    for i in range(5):
        history.add(Message(role=Role.USER, content=f"msg{i}"))

    roles = [m.role for m in history.messages]
    # system always retained
    assert roles[0] == Role.SYSTEM
    # total respects max_size
    assert len(history.messages) <= 3
    # oldest user messages trimmed, newest kept
    assert history.messages[-1].content == "msg4"


async def test_empty_llm_reply_falls_back(monkeypatch) -> None:
    # A reasoning model can finish a turn with no tool call and empty content
    # (everything went to its thinking channel). handle() must not return "",
    # which adapters like Telegram silently drop — it returns a fallback instead.
    settings = Settings()
    settings.logging.trace_file = None  # no file writes during the test
    agent = Agent(settings)

    async def fake_chat(messages, tools=None, on_token=None, on_reasoning=None):
        return Message(role=Role.ASSISTANT, content="   \n")

    monkeypatch.setattr(agent._llm, "chat", fake_chat)

    reply = await agent.handle("u1", "current speed internet")
    assert reply == _EMPTY_REPLY_FALLBACK


async def test_empty_llm_reply_falls_back_to_tool_result(monkeypatch) -> None:
    # Regression: a local model can stream zero tokens on the turn that summarises
    # a tool result. The tool already produced the answer (here: a share link and
    # passcode), so handle() must return that instead of the generic apology.
    settings = Settings()
    settings.logging.trace_file = None
    agent = Agent(settings)

    @tool(description="Create a share link")
    async def share_link() -> str:
        return "Share link is live!\nPasscode: 8vug6dxhdk"

    agent.registry.register_callable(share_link)

    calls = 0

    async def fake_chat(messages, tools=None, on_token=None, on_reasoning=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="c1", name="share_link", arguments={})],
            )
        return Message(role=Role.ASSISTANT, content="")

    monkeypatch.setattr(agent._llm, "chat", fake_chat)

    reply = await agent.handle("u1", "send me the share link")
    assert "8vug6dxhdk" in reply
    assert reply != _EMPTY_REPLY_FALLBACK


async def test_nonempty_llm_reply_passes_through(monkeypatch) -> None:
    settings = Settings()
    settings.logging.trace_file = None
    agent = Agent(settings)

    async def fake_chat(messages, tools=None, on_token=None, on_reasoning=None):
        return Message(role=Role.ASSISTANT, content="Download: 61 Mbps")

    monkeypatch.setattr(agent._llm, "chat", fake_chat)

    reply = await agent.handle("u1", "current speed internet")
    assert reply == "Download: 61 Mbps"


TOGGLE_TOOL = '''
from lesysbot.mcp import tool

@tool(description="pingy")
async def pingy() -> str:
    return "pong"
'''


async def test_enable_disable_from_another_process_applies_live(tmp_path, monkeypatch) -> None:
    """A toggle written to the state file by anyone else reaches a running agent.

    `lesysbot tools enable/disable` and a hand edit both mutate this file rather
    than this process's registry. Before Agent._watch_tool_state they only took
    effect on restart.
    """
    import asyncio
    import json

    from lesysbot.core.config import resolve_paths

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / ".lesysbot"))
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "tools" / "t"
    pkg.mkdir(parents=True)
    (pkg / "tool.py").write_text(TOGGLE_TOOL)

    settings = Settings.load()
    resolve_paths(settings)
    agent = Agent(settings)
    await agent.setup()
    await asyncio.sleep(0.5)  # let the watcher attach before we write
    assert agent.registry.is_enabled("pingy")

    Path(settings.mcp.state_file).write_text(json.dumps({"disabled": ["pingy"]}))

    for _ in range(60):
        await asyncio.sleep(0.25)
        if not agent.registry.is_enabled("pingy"):
            break
    assert not agent.registry.is_enabled("pingy"), "the agent never picked up the change"
    # ...and it's genuinely gone, not just flagged: the LLM can no longer see it.
    assert agent.registry.get_openai_schemas() == []
