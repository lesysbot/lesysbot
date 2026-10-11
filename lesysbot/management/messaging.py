"""The panel's Messaging form: Telegram/Discord setup without a text editor.

The browser gets a *description* of each token — saved, from an environment
variable, or missing, plus its last four characters so you can tell two bots
apart — never the token itself. A save sends a token only when one was typed;
an omitted token keeps the saved value. Everything is written into
``config.yaml`` through :mod:`configedit`, so the file keeps its comments.
"""
from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from typing import Any

from lesysbot.core.config import _ENV_REF, Settings, _expand_env
from lesysbot.core.redact import redact
from lesysbot.management import configedit as ce

PROVIDERS = ("cli", "telegram", "discord")
_REMOTE = ("telegram", "discord")
_NOTICE_KEYS = {"enabled": bool, "speedtest": bool, "speedtest_mb": float}


def _token_info(value: Any) -> dict:
    if not isinstance(value, str) or not value.strip():
        return {"state": "empty"}
    if ce.is_env_ref(value):
        var = _ENV_REF.fullmatch(value.strip()).group(1)
        return {"state": "env", "env_var": var, "env_set": bool(os.environ.get(var))}
    return {"state": "set", "hint": value[-4:] if len(value) >= 12 else ""}


def view(text: str, running: Settings) -> dict:
    """What the form shows, built from the file as written (not env-expanded)."""
    data = ce.load(text)
    defaults = Settings().messaging.model_dump()
    out: dict[str, Any] = {
        "provider": ce.get(data, ("messaging", "provider")) or defaults["provider"],
        "running_provider": running.messaging.provider,
    }
    for name in _REMOTE:
        out[name] = {
            "token": _token_info(ce.get(data, ("messaging", name, "token"))),
            "allowed_user_ids": ce.get(data, ("messaging", name, "allowed_user_ids")) or [],
        }
    notice = dict(defaults["startup_notice"])
    notice.update(ce.get(data, ("messaging", "startup_notice")) or {})
    out["startup_notice"] = notice
    # Does the running service already use what's saved? (Config is read at start.)
    try:
        saved = Settings(**_expand_env(copy.deepcopy(data), [])).messaging.model_dump()
        out["restart_needed"] = saved != running.messaging.model_dump()
    except Exception:
        out["restart_needed"] = True
    return out


def _ids(value: Any, label: str, *, allow_str: bool = False) -> list:
    """Accept a list or a comma/space separated string of ids."""
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).replace(",", " ").split()
    out = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except ValueError:
            if not allow_str:
                raise ValueError(f"{label}: {s!r} is not a numeric id") from None
            out.append(s)
    return out


def apply(text: str, form: dict) -> tuple[str, dict]:
    """Merge the submitted ``form`` into config ``text``.

    Returns ``(new_text, data)``. Raises ``ValueError`` with a message meant
    for a person when the form doesn't describe a working setup.
    """
    data = ce.load(text)
    new = copy.deepcopy(data)
    changes: dict[ce.Path_, Any] = {}

    defaults = Settings().messaging.model_dump()

    def setv(path, value):
        # A key the file doesn't have is compared with its default, so saving
        # the form untouched doesn't spell every default out into config.yaml.
        current = ce.get(data, path)
        if current is None:
            current = ce.get({"messaging": defaults}, path)
        if current != value:
            changes[path] = value
            ce.put(new, path, value)

    provider = form.get("provider", ce.get(data, ("messaging", "provider")) or "cli")
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}")
    setv(("messaging", "provider"), provider)

    for name in _REMOTE:
        section = form.get(name) or {}
        if "token" in section and section["token"] is not None:
            token = str(section["token"]).strip()
            if token == ce.HIDDEN:
                raise ValueError(f"{name} token: type the token itself")
            setv(("messaging", name, "token"), token)
        if "allowed_user_ids" in section:
            setv(("messaging", name, "allowed_user_ids"),
                 _ids(section["allowed_user_ids"], f"{name.title()} allowed user ids"))

    notice = form.get("startup_notice")
    if isinstance(notice, dict):
        for key, kind in _NOTICE_KEYS.items():
            if key in notice:
                setv(("messaging", "startup_notice", key), kind(notice[key]))
        if "notify" in notice:
            setv(("messaging", "startup_notice", "notify"),
                 _ids(notice["notify"], "Startup notice recipients", allow_str=True))

    if provider in _REMOTE:
        token = ce.get(new, ("messaging", provider, "token"))
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{provider.title()} needs a bot token before it can be the provider.")

    Settings(**_expand_env(copy.deepcopy(new), []))   # schema check; raises on bad values
    if not changes:
        return text, new
    return ce.apply(text, changes, new), new


# -- "Test token" -----------------------------------------------------------------
def _get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot (https://lesysbot.github.io, 1)",
                                               **headers})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


def check_token(provider: str, token: str) -> dict:
    """Ask the platform who this token belongs to. Never echoes the token."""
    token = token.strip()
    if ce.is_env_ref(token):
        token = os.environ.get(_ENV_REF.fullmatch(token).group(1), "")
    if not token:
        return {"ok": False, "error": "No token to test."}
    try:
        if provider == "telegram":
            me = _get_json(f"https://api.telegram.org/bot{token}/getMe", {}).get("result") or {}
            return {"ok": True, "bot": "@" + str(me.get("username", "?")),
                    "name": me.get("first_name", "")}
        if provider == "discord":
            me = _get_json("https://discord.com/api/v10/users/@me",
                           {"Authorization": f"Bot {token}"})
            return {"ok": True, "bot": str(me.get("username", "?")), "id": me.get("id")}
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            return {"ok": False, "error": f"{provider.title()} rejected this token."}
        return {"ok": False, "error": f"{provider.title()} answered HTTP {e.code}."}
    except Exception as e:  # network down, DNS, timeout
        msg = redact(str(getattr(e, "reason", e))).replace(token, "<redacted>")
        return {"ok": False, "error": f"Could not reach {provider.title()}: {msg}"}
