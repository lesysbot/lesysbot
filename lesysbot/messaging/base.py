from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable


# Handler receives (user_id, text, **kwargs) and returns a reply string.
# The optional on_token kwarg is used by streaming-capable adapters (e.g. CLI).
MessageHandler = Callable[..., Awaitable[str]]


class MessagingAdapter(ABC):
    """All messaging backends implement this interface."""

    @property
    def ready(self) -> asyncio.Event:
        """Set by `start()` once the adapter can `send()` — the startup notice
        waits on it. Lazily created so subclasses need no __init__ changes."""
        event = getattr(self, "_ready_event", None)
        if event is None:
            event = self._ready_event = asyncio.Event()
        return event

    @abstractmethod
    async def start(self, handler: MessageHandler) -> None:
        """Start listening for messages; call handler for each one."""
        ...

    @abstractmethod
    async def send(self, user_id: str, text: str) -> None:
        """Send a message to a specific user."""
        ...

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        """Request user confirmation before a tool runs.

        The default implementation auto-approves. Override in adapters that
        support interactive confirmation (e.g. CLI prompt, Telegram/Discord
        buttons).
        """
        return True


def split_message(text: str, max_len: int) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters.

    Every chat platform caps a single message (Telegram at 4096, Discord at
    2000) and rejects anything over it, so a long tool result has to be sent as
    several messages rather than dropped.

    Empty/whitespace-only input yields no chunks — both APIs reject an empty
    message body, which would otherwise surface as a confusing send failure
    instead of the no-op it really is.
    """
    if not text.strip():
        return []
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
