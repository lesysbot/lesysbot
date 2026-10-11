"""Editing config.yaml from the control panel without leaking or mangling it.

Two jobs, both about the browser never holding a credential:

* **Masking.** The panel's YAML editor and its Messaging form never receive a
  bot token or API key. Literal secrets go out as :data:`HIDDEN`; a ``${VAR}``
  reference is not a secret (it names one) and goes out as-is. On save, a value
  still reading :data:`HIDDEN` is put back from the file on disk, so "leave it
  alone" keeps the saved token without the page ever having seen it.

* **Surgical writes.** ``yaml.safe_dump`` would discard every comment the
  wizard and the user wrote, so changes are applied line by line
  (:func:`set_value`) and the result is re-parsed and compared with what was
  intended. Anything the line editor can't do exactly — an odd layout, flow
  mappings, anchors — falls back to a full dump: comments lost, values right.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml

from lesysbot.core.config import _ENV_REF

# Shown in place of a saved secret. Saving it back means "keep what's there".
HIDDEN = "<hidden>"

Path_ = tuple[str, ...]

# Always masked. Bot tokens are credentials whatever their length.
TOKEN_PATHS: tuple[Path_, ...] = (
    ("messaging", "telegram", "token"),
    ("messaging", "discord", "token"),
)
# llm.api_key is "ollama" on a default install — masking a placeholder only
# hides what backend you use. Same threshold as core/redact._MIN_SECRET_LEN.
API_KEY_PATH: Path_ = ("llm", "api_key")
_MIN_SECRET_LEN = 12
SECRET_PATHS: tuple[Path_, ...] = TOKEN_PATHS + (API_KEY_PATH,)


# -- dict helpers ---------------------------------------------------------------
def get(data: Any, path: Path_) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def put(data: dict, path: Path_, value: Any) -> None:
    for key in path[:-1]:
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data = data[key]
    data[path[-1]] = value


def is_env_ref(value: Any) -> bool:
    """True for a value that only *names* a secret, e.g. ``${TELEGRAM_TOKEN}``."""
    return isinstance(value, str) and bool(_ENV_REF.fullmatch(value.strip()))


def is_secret(path: Path_, value: Any) -> bool:
    if not isinstance(value, str) or not value or value == HIDDEN or is_env_ref(value):
        return False
    if path == API_KEY_PATH:
        return len(value) >= _MIN_SECRET_LEN
    return True


def load(text: str) -> dict:
    data = yaml.safe_load(text) if text.strip() else {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("config must be a mapping")
    return data


# -- line-level YAML editing ----------------------------------------------------
_KEY = re.compile(
    r"^(?P<indent> *)(?P<key>[A-Za-z_][\w-]*|\"[^\"]*\"|'[^']*')[ \t]*:(?:[ \t]+(?P<rest>.*))?$"
)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_filler(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _trailing_comment(rest: str) -> str:
    """The ``# comment`` after a scalar, if any (quote-aware)."""
    quote = None
    i = 0
    while i < len(rest):
        c = rest[i]
        if quote == "'":
            if c == "'":
                if rest[i + 1:i + 2] == "'":
                    i += 1
                else:
                    quote = None
        elif quote == '"':
            if c == "\\":
                i += 1
            elif c == '"':
                quote = None
        elif c in "'\"" and (i == 0 or rest[i - 1] in " \t[,{"):
            quote = c
        elif c == "#" and (i == 0 or rest[i - 1] in " \t"):
            return rest[i:].rstrip()
        i += 1
    return ""


_PLAIN = re.compile(r"[A-Za-z][A-Za-z_-]*")


def _render(value: Any) -> str:
    # JSON is valid YAML for every scalar/list this module writes. Strings are
    # quoted — so a token like "123:abc" can't be misread — except plain words
    # such as ``discord``, which read back unchanged and look like the rest of
    # a hand-written file.
    if (isinstance(value, str) and _PLAIN.fullmatch(value)
            and yaml.safe_load(value) == value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _block_end(lines: list[str], start: int, end: int, indent: int) -> int:
    """First line after the value that begins at ``start`` (exclusive of
    trailing blank/comment lines, which belong to whatever follows)."""
    j, last = start, start
    while j < end:
        ln = lines[j]
        if _is_filler(ln):
            j += 1
            continue
        ind = _indent(ln)
        if ind > indent or (ind == indent and ln.lstrip().startswith("- ")):
            j += 1
            last = j
            continue
        break
    return last


def set_value(text: str, path: Path_, value: Any) -> str | None:
    """Set ``path`` to ``value`` in YAML ``text``, keeping comments and layout.

    Returns ``None`` when the layout is beyond this line editor; callers then
    fall back to a full dump (see :func:`apply`).
    """
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start, end, parent_indent = 0, len(lines), -1

    for level, key in enumerate(path):
        child_indent = None
        found = None
        stop = end
        for j in range(start, end):
            ln = lines[j]
            if _is_filler(ln):
                continue
            ind = _indent(ln)
            if ind <= parent_indent:
                stop = j
                break
            if child_indent is None:
                child_indent = ind
            if ind != child_indent:
                continue
            m = _KEY.match(ln.rstrip("\r\n"))
            if m is None:
                if ln.lstrip().startswith("- "):
                    return None          # a list where a mapping was expected
                continue
            if m.group("key").strip("\"'") == key:
                found = j
                break

        if found is None:
            # Insert the missing tail of the path at the end of this block.
            ind = child_indent if child_indent is not None else parent_indent + 2
            step = 2
            insert_at = _block_end(lines, start, stop, parent_indent) if parent_indent >= 0 else stop
            if parent_indent < 0:
                # top level: append, separated by a blank line
                while insert_at > 0 and not lines[insert_at - 1].strip():
                    insert_at -= 1
            new = []
            if parent_indent < 0 and insert_at > 0:
                new.append("\n")
            for k, name in enumerate(path[level:-1]):
                new.append(" " * (ind + k * step) + f"{name}:\n")
            new.append(" " * (ind + (len(path) - level - 1) * step)
                       + f"{path[-1]}: {_render(value)}\n")
            lines[insert_at:insert_at] = new
            return "".join(lines)

        m = _KEY.match(lines[found].rstrip("\r\n"))
        blk_end = _block_end(lines, found + 1, end, child_indent)
        if level == len(path) - 1:
            rest = (m.group("rest") or "").strip()
            if rest.startswith(("&", "*", "!", "{")):
                return None              # anchors, aliases, tags, flow maps
            comment = "" if rest.startswith(("|", ">")) else _trailing_comment(rest)
            if rest.startswith("#"):
                comment = rest
            line = f"{m.group('indent')}{m.group('key')}: {_render(value)}"
            if comment:
                line += "  " + comment
            lines[found:blk_end] = [line + "\n"]
            return "".join(lines)

        rest = (m.group("rest") or "").strip()
        if rest and not rest.startswith("#"):
            return None                  # inline value where a mapping should be
        start, end, parent_indent = found + 1, blk_end, child_indent
    return None


def apply(text: str, changes: dict[Path_, Any], expected: dict) -> str:
    """Apply ``changes`` to ``text``; verify the result parses to ``expected``.

    If any step fails, or the parsed result differs, the whole file is
    re-serialized from ``expected`` instead — correct values beat comments.
    """
    out: str | None = text
    for path, value in changes.items():
        out = set_value(out, path, value) if out is not None else None
    if out is not None:
        try:
            if load(out) == expected:
                return out
        except (yaml.YAMLError, ValueError):
            pass
    return yaml.safe_dump(expected, sort_keys=False, allow_unicode=True)


# -- masking --------------------------------------------------------------------
def mask(text: str) -> str:
    """``text`` with every literal secret replaced by :data:`HIDDEN`."""
    data = load(text)
    masked = copy.deepcopy(data)
    changes = {}
    for path in SECRET_PATHS:
        if is_secret(path, get(data, path)):
            changes[path] = HIDDEN
            put(masked, path, HIDDEN)
    return apply(text, changes, masked) if changes else text


def unmask(new_text: str, old_text: str) -> tuple[str, dict]:
    """Put saved secrets back wherever ``new_text`` still says :data:`HIDDEN`.

    Returns the text to write and its parsed data. Raises ``ValueError`` when a
    value reads :data:`HIDDEN` but there is nothing saved to restore.
    """
    data = load(new_text)
    old = load(old_text) if old_text else {}
    restored = copy.deepcopy(data)
    changes = {}
    for path in SECRET_PATHS:
        if get(data, path) != HIDDEN:
            continue
        real = get(old, path)
        if not isinstance(real, str) or real == HIDDEN:
            raise ValueError(f"{'.'.join(path)} is {HIDDEN} but nothing is saved "
                             "there — type the value in.")
        changes[path] = real
        put(restored, path, real)
    if not changes:
        return new_text, data
    return apply(new_text, changes, restored), restored
