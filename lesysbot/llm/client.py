from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from openai import AsyncOpenAI

from lesysbot.core.config import LLMConfig
from lesysbot.core.types import Message, Role, ToolCall

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible client — works with Ollama, vLLM, LlamaCpp, OpenAI."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client. Call this before the event loop it
        was created in is torn down (e.g. one-shot `asyncio.run` probes) — otherwise
        its finalizer runs on a closed loop and logs 'Event loop is closed'."""
        await self._client.close()

    async def health(self) -> dict[str, Any]:
        """Probe the LLM backend with a cheap /models call.

        Returns a dict: on success
        {ok, latency_ms, base_url, model, model_available, models}, and on failure
        {ok: False, error, base_url, model}. Uses a short 5 s timeout (not the long
        chat timeout) so an unreachable backend fails fast.
        """
        base = {"base_url": self._config.base_url, "model": self._config.model}
        t0 = time.perf_counter()
        try:
            result = await self._client.with_options(timeout=5.0).models.list()
            ids = [m.id for m in getattr(result, "data", [])]
            return {
                **base,
                "ok": True,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "model_available": self._config.model in ids,
                "models": ids[:50],
            }
        except Exception as e:
            return {**base, "ok": False, "error": str(e)}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> Message:
        """Send a chat request, streaming answer text via on_token and (for
        reasoning models that expose it) chain-of-thought via on_reasoning."""
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug("LLM request: model=%s, messages=%d", self._config.model, len(messages))

        content_parts: list[str] = []
        tool_call_acc: dict[int, dict[str, str]] = {}

        response = await self._client.chat.completions.create(**kwargs)
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Some OpenAI-compatible reasoning models stream chain-of-thought in a
            # separate `reasoning_content` field (not part of the final message).
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and on_reasoning:
                on_reasoning(reasoning)

            if delta.content:
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    i = tc.index
                    if i not in tool_call_acc:
                        tool_call_acc[i] = {"id": "", "name": "", "args": ""}
                    if tc.id:
                        tool_call_acc[i]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_call_acc[i]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_call_acc[i]["args"] += tc.function.arguments

        tool_calls = None
        if tool_call_acc:
            tool_calls = [
                ToolCall(
                    id=v["id"],
                    name=v["name"],
                    arguments=json.loads(v["args"] or "{}"),
                )
                for _, v in sorted(tool_call_acc.items())
            ]

        return Message(
            role=Role.ASSISTANT,
            content="".join(content_parts),
            tool_calls=tool_calls,
        )
