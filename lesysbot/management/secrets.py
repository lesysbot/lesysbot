"""Hide credentials in the config text the panel hands to a browser.

The Config tab is the one place a whole ``config.yaml`` — bot tokens and API key
included — leaves the process as a payload something else renders: a browser
tab left open on a shared screen, a screenshot pasted into an issue, a page
saved to disk. Logs are already covered (:mod:`lesysbot.core.redact`); this is
the same rule for the panel.

So the panel never sends the real values. Each credential goes out as
``****`` + its last four characters, and :func:`restore` swaps the stored value
back in before the file is written. Editing the model or a log path therefore
costs nobody a retyped token, and setting a *new* token still works — anything
that isn't the exact mask we sent is taken literally.

Masking is line-level rather than parse-and-redump because the text is the
user's own file: comments, key order and spacing have to survive the round
trip. It also still works on a config that no longer parses, which is exactly
when someone opens the panel to fix it.
"""

from __future__ import annotations

import re

from lesysbot.core.redact import MIN_SECRET_LEN

#: What replaces everything but the tail of a credential.
MASK_PREFIX = "****"

#: How much of the value survives — enough to tell two tokens apart, far too
#: little to use.
VISIBLE_CHARS = 4

# The keys that carry a credential: ``messaging.*.token`` and ``llm.api_key``.
# Matched by key name at line level rather than by path, so this holds for a
# file that doesn't parse. `max_tokens` and friends don't match — the key is
# anchored whole.
_SECRET_LINE = re.compile(
    r"^(?P<lead>[^\S\n]*(?:token|api_key)[^\S\n]*:[^\S\n]*)"
    r"(?P<quote>['\"]?)(?P<value>[^'\"#\n]*?)(?P=quote)"
    r"(?P<tail>[^\S\n]*(?:#[^\n]*)?)$",
    re.MULTILINE,
)


class AmbiguousMask(ValueError):
    """Two different credentials mask to the same text — can't restore blind."""


def mask_value(value: str) -> str:
    """``"0123456789:AAbbCC"`` → ``"****bbCC"``."""
    return MASK_PREFIX + value[-VISIBLE_CHARS:]


def _is_secret(value: str) -> bool:
    """Worth hiding?

    Short values are left alone for the reason :mod:`~lesysbot.core.redact`
    gives — ``api_key: ollama`` on a default install is a placeholder, and
    masking it would only make the file harder to read. A ``${VAR}`` reference
    holds no secret either: the name is the point, and hiding it would look
    like the config lost its value. A mask is shorter than the threshold, so
    masking is idempotent and a mask is never mistaken for a new credential.
    """
    return len(value) >= MIN_SECRET_LEN and not value.startswith("${")


def mask(text: str) -> str:
    """Return *text* with every credential replaced by :func:`mask_value`."""
    def hide(m: re.Match[str]) -> str:
        if not _is_secret(m["value"]):
            return m[0]
        return m["lead"] + m["quote"] + mask_value(m["value"]) + m["quote"] + m["tail"]

    return _SECRET_LINE.sub(hide, text)


def is_masked(text: str) -> bool:
    """True when :func:`mask` would hide something — drives the panel's note."""
    return any(_is_secret(m["value"]) for m in _SECRET_LINE.finditer(text))


def restore(text: str, stored: str) -> str:
    """Put the credentials from *stored* back into edited *text*.

    A value that still equals the mask we sent is replaced by the one on disk;
    anything else is the user typing a real value and passes through untouched.

    Raises :class:`AmbiguousMask` if two stored credentials share a mask — one
    chance in 65 536, and guessing which is which would silently swap somebody's
    Telegram and Discord tokens.
    """
    originals: dict[str, str] = {}
    ambiguous: set[str] = set()
    for m in _SECRET_LINE.finditer(stored):
        value = m["value"]
        if not _is_secret(value):
            continue
        masked = mask_value(value)
        if originals.setdefault(masked, value) != value:
            ambiguous.add(masked)
    if not originals:
        return text

    def swap(m: re.Match[str]) -> str:
        value = m["value"]
        if value not in originals:
            return m[0]
        if value in ambiguous:
            raise AmbiguousMask(
                f"{value!r} matches more than one saved credential — type the "
                f"value you want in full, or edit the config file directly.")
        return m["lead"] + m["quote"] + originals[value] + m["quote"] + m["tail"]

    return _SECRET_LINE.sub(swap, text)
