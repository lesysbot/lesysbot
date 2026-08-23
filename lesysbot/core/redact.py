"""Keep credentials out of the logs.

httpx logs every request at INFO, and the Telegram Bot API carries the bot
token in the URL *path* (``/bot<token>/getUpdates``) — so a service running at
the default INFO level writes the token to disk a few thousand times a day.
Log files are the first thing pasted into a bug report, so the token must not
travel with them.

Redaction happens at the logging layer rather than at each call site because
the leak is not ours to fix at the source: it comes from httpx (and any other
library that logs a URL). Filtering on the way out catches every producer,
including ones added later.

Two sources of truth for what counts as a secret:

* **Patterns** (:data:`_PATTERNS`) — the shapes credentials come in. These work
  with no configuration at all, which matters because the worst leak (the
  Telegram URL) is logged by a library before anything registers a secret.
* **Registered values** (:func:`add_secret`) — the exact strings from the
  active config, so an OpenAI key or a Discord token is scrubbed even when it
  shows up somewhere no pattern anticipated.

Registration deliberately ignores short values: ``llm.api_key`` is ``"ollama"``
on a default install, and treating a six-letter dictionary word as a secret
would replace it everywhere and make the logs unreadable. See
:data:`MIN_SECRET_LEN`.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lesysbot.core.config import Settings

PLACEHOLDER = "<redacted>"

# Values shorter than this are never registered as secrets: real credentials
# clear it easily, while the common placeholders ("ollama", "vllm", "none")
# do not — and redacting one of those would rewrite unrelated log text. Public
# because the control panel masks the same values on the same rule
# (``management/secrets.py``) — one threshold, both surfaces.
MIN_SECRET_LEN = 12

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Telegram bot token in an API URL: /bot<digits>:<35-ish chars>/method.
    # Keeps the "bot" prefix so the line still reads as a Telegram call.
    re.compile(r"(?<=bot)(\d{6,}:[A-Za-z0-9_-]{20,})"),
    # Telegram token standing alone (config echo, error message, traceback).
    re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{30,}\b"),
    # Discord bot token: three base64url parts — the app's snowflake, a
    # 6-character timestamp, then an HMAC (e.g. "MTIz….GhIjKl.mNoPqR…").
    # The fixed-length middle part is what keeps this off ordinary dotted text.
    re.compile(r"\b[A-Za-z0-9_-]{23,30}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b"),
    # The mfa.<hmac> form, in case a user token is pasted in by mistake.
    re.compile(r"\bmfa\.[A-Za-z0-9_-]{20,}\b"),
    # OpenAI-style keys, including the project-scoped sk-proj- form.
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
)

# Exact strings pulled from the active config. Module-global because logging is
# process-wide; a set keeps re-registration idempotent.
_secrets: set[str] = set()


def add_secret(value: str | None) -> None:
    """Register *value* for exact-match redaction.

    Ignores anything falsy or shorter than :data:`MIN_SECRET_LEN` — see the
    module docstring on why ``api_key: "ollama"`` must not become a secret.
    """
    if value and len(value) >= MIN_SECRET_LEN:
        _secrets.add(value)


def register_settings_secrets(settings: Settings) -> None:
    """Register every credential the active config carries."""
    add_secret(settings.messaging.telegram.token)
    add_secret(settings.messaging.discord.token)
    add_secret(settings.llm.api_key)


def redact(text: str) -> str:
    """Return *text* with known credentials replaced by :data:`PLACEHOLDER`.

    Idempotent: the placeholder matches none of the patterns, so re-running it
    over already-redacted text is a no-op. That matters because one filter
    instance is attached to several handlers.
    """
    # Registered values first: an exact match is more specific than a pattern,
    # and scrubbing it early keeps a pattern from splitting it in half.
    for secret in _secrets:
        if secret in text:
            text = text.replace(secret, PLACEHOLDER)
    for pattern in _PATTERNS:
        text = pattern.sub(PLACEHOLDER, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrub credentials from a record's message.

    Attached to handlers rather than loggers: a logger's filters do not run on
    records propagated up from child loggers, which is exactly the traffic that
    needs scrubbing (``httpx`` logs to its own logger).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed %-args; let it through
            return True
        cleaned = redact(message)
        if cleaned != message:
            # Collapse to a plain string: the args have already been folded in,
            # and leaving them would re-introduce the secret at format time.
            record.msg = cleaned
            record.args = None
        return True


class RedactingFormatter(logging.Formatter):
    """Formatter that scrubs its own output, tracebacks included.

    :class:`RedactingFilter` only sees the message; an exception rendered by
    the formatter can carry a URL with the token in it (httpx puts the request
    URL on the exception). Redacting the fully formatted string is the only
    place that covers both.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
