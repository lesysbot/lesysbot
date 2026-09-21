"""Build a complete :class:`~lesysbot.setup.wizard.WizardState` with no prompts.

``lesysbot setup --yes`` answers the wizard from defaults plus ``LESYSBOT_SETUP_*``
environment variables, so the one-command installer — and anyone scripting an
install — never needs a terminal. The defaults are exactly what pressing Enter
through the interactive wizard would give you: Ollama on localhost, terminal-only,
service enabled at boot.

Only the *answers* live here. Everything that acts on them (writing config,
seeding tools, installing the service, the dashboard) is the same
:mod:`lesysbot.setup.apply` code the interactive path runs.
"""

from __future__ import annotations

import os
import secrets
import string

from lesysbot.setup.wizard import DEFAULT_OLLAMA_MODEL, SetupAborted, WizardState, parse_allowed_ids

ENV_PREFIX = "LESYSBOT_SETUP_"

#: ``llm_choice`` values, keyed by the name accepted in ``LESYSBOT_SETUP_LLM``.
_LLM_CHOICES = {"ollama": 1, "openai": 2, "vllm": 3, "custom": 4}

_LLM_DEFAULTS = {
    # choice: (base_url, model, api_key)
    1: ("http://localhost:11434/v1", DEFAULT_OLLAMA_MODEL, "ollama"),
    2: ("https://api.openai.com/v1", "gpt-4o", ""),
    3: ("http://localhost:8000/v1", "meta-llama/Llama-3.2-8B-Instruct", "vllm"),
    4: ("http://localhost:8000/v1", DEFAULT_OLLAMA_MODEL, "none"),
}

_PROVIDER_CHOICES = {"cli": 1, "telegram": 2, "discord": 3}

# Letters and digits only: this password is written into a Docker `.env` and a
# KEY=VALUE file, neither of which quotes. Punctuation buys entropy we can get
# from length instead, and costs a class of parsing bugs.
_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generated_password(length: int = 20) -> str:
    """A URL/env-safe random password (used when none was configured)."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def _get(env: dict[str, str], name: str, default: str = "") -> str:
    return (env.get(ENV_PREFIX + name) or default).strip()


def _truthy(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.lower() not in ("0", "false", "no", "off")


def _abort(message: str, hint: str) -> None:
    # Printed rather than raised through the UI: an unattended run may have no
    # terminal at all, and this has to survive being captured in a CI log.
    print(f"\n  ✗  {message}\n     {hint}\n")
    raise SetupAborted(1)


def _messaging(env: dict[str, str], st: WizardState) -> None:
    """Fill the messaging half of *st* — provider, token, allow-list."""
    provider = _get(env, "PROVIDER", "cli").lower()
    if provider not in _PROVIDER_CHOICES:
        _abort(
            f"{ENV_PREFIX}PROVIDER={provider!r} is not one of: "
            + ", ".join(_PROVIDER_CHOICES),
            "Leave it unset for terminal-only.",
        )
    st.msg_provider = provider
    st.msg_choice = _PROVIDER_CHOICES[provider]
    if provider == "cli":
        return

    label = provider.capitalize()
    token = _get(env, f"{provider.upper()}_TOKEN")
    if not token:
        _abort(
            f"{label} was requested but no bot token was given.",
            f"Set {ENV_PREFIX}{provider.upper()}_TOKEN.",
        )
    raw_ids = _get(env, f"{provider.upper()}_ALLOWED_IDS")
    parsed = parse_allowed_ids(raw_ids)
    if parsed is None:
        # Same rule as the interactive wizard: an empty allow-list means anyone
        # who can reach the bot runs tools on this machine.
        _abort(
            f"{label} needs an allow-list of numeric user IDs"
            + (f", and {raw_ids!r} isn't one." if raw_ids else "."),
            f"Set {ENV_PREFIX}{provider.upper()}_ALLOWED_IDS=123456789 "
            "(comma-separated for several).",
        )
    assert parsed is not None  # for type checkers; _abort raises
    if provider == "telegram":
        st.tg_token = token
        st.tg_raw_ids, st.tg_allowed_ids = parsed
    else:
        st.dc_token = token
        st.dc_raw_ids, st.dc_allowed_ids = parsed


def state_from_env(env: dict[str, str] | None = None) -> WizardState:
    """The wizard's answers, taken from defaults and ``LESYSBOT_SETUP_*``.

    Raises :class:`SetupAborted` (after printing why, and naming the variable to
    set) rather than guessing when a required value is missing — a half-configured
    remote bot is worse than a failed install.
    """
    env = dict(os.environ if env is None else env)
    st = WizardState()

    backend = _get(env, "LLM", "ollama").lower()
    if backend not in _LLM_CHOICES:
        _abort(
            f"{ENV_PREFIX}LLM={backend!r} is not one of: " + ", ".join(_LLM_CHOICES),
            "Leave it unset for Ollama.",
        )
    st.llm_choice = _LLM_CHOICES[backend]
    base_url, model, api_key = _LLM_DEFAULTS[st.llm_choice]
    st.llm_base_url = _get(env, "BASE_URL", base_url)
    # Deliberately never shells out to `ollama list`/`ollama pull` the way
    # step_llm does: the installer has already pulled the model, and an
    # unattended run must not block on a multi-gigabyte download it didn't ask for.
    st.llm_model = _get(env, "MODEL", model)
    st.llm_api_key = _get(env, "API_KEY", api_key)
    if backend == "openai" and not st.llm_api_key:
        _abort(
            "OpenAI was requested but no API key was given.",
            f"Set {ENV_PREFIX}API_KEY=sk-…",
        )

    _messaging(env, st)

    st.needs_service = True
    st.auto_start = _truthy(_get(env, "AUTOSTART"), True)
    st.auto_choice = 1 if st.auto_start else 2
    return st
