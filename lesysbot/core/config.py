from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ${VAR} references in config.yaml string values are expanded from the
# environment at load time. Unset variables are left as the literal text, so a
# value like "${TELEGRAM_TOKEN}" only works once the variable actually exists —
# from_yaml() collects such misses so the caller can warn about them.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any, missing: list[str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            var = match.group(1)
            if var in os.environ:
                return os.environ[var]
            missing.append(var)
            return match.group(0)

        return _ENV_REF.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, missing) for v in value]
    return value


class TelegramConfig(BaseModel):
    token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    # A single bot token from the Discord developer portal. Note the bot also
    # needs the Message Content intent enabled there, or the gateway delivers
    # every message with an empty `content` and the bot looks deaf.
    token: str = ""
    # Numeric Discord user ids (snowflakes). Empty = allow everyone, which on
    # Discord means anyone who shares a server with the bot can DM it.
    allowed_user_ids: list[int] = Field(default_factory=list)


class StartupNoticeConfig(BaseModel):
    # Ping the user when the bot comes up — for an installed background service
    # that means right after the machine boots or wakes — with a short system
    # report (CPU/GPU temp, disk, internet speed; each only if the host can
    # answer). Remote providers only: the CLI never sends it.
    enabled: bool = True
    # Who to ping: Telegram chat ids, or Discord user/channel ids. Both fall
    # back to their allowed_user_ids when empty.
    notify: list[int | str] = Field(default_factory=list)
    # Include an internet speed measurement (downloads `speedtest_mb` MB).
    speedtest: bool = True
    speedtest_mb: float = 5.0


class MessagingConfig(BaseModel):
    provider: str = "cli"  # cli | telegram | discord
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    startup_notice: StartupNoticeConfig = Field(default_factory=StartupNoticeConfig)


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3.5:4b"
    api_key: str = "ollama"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


class MCPConfig(BaseModel):
    tools_dir: str = "./tools"
    hot_reload: bool = True
    # Lock file recording where installed packages came from (`lesysbot
    # install`): kind, repo, pinned commit, version. Relative paths anchor to
    # the config dir (so ~/.lesysbot/lesysbot.lock.json when installed).
    #
    # The default changed from `tools.lock.json` when dashboards became
    # installable and the lock stopped being about tools. A config still naming
    # the old file is honoured as-is — it is a path, so pointing at it simply
    # works — and `ArtifactLock` migrates a v1 file found beside the new one.
    lock_file: str = "lesysbot.lock.json"
    # Persisted set of tools disabled via `lesysbot tools disable`. Relative
    # paths anchor to the config dir (so ~/.lesysbot/tool_state.json for an
    # installed setup), like tools_dir/logs. The bot watches this file, so a
    # change from the CLI reaches a running bot within a second (set null to
    # disable persistence).
    state_file: str | None = "tool_state.json"


class AgentConfig(BaseModel):
    system_prompt: str = (
        "You are a helpful assistant with access to tools. "
        "Use tools when they help answer the user's question. "
        "Be concise and clear."
    )
    max_history: int = 50
    max_tool_calls: int = 10


class LogConfig(BaseModel):
    level: str = "INFO"
    file: str | None = "logs/lesysbot.log"
    trace_file: str | None = "logs/traces.jsonl"
    # Time-based rotation for both the log and the trace file (applied via
    # TimedRotatingFileHandler). `when` is the rollover interval ("midnight",
    # "H", "D", "W0".."W6", …); `backup_count` is how many rotated files to keep.
    when: str = "midnight"
    backup_count: int = 7


class ManagementConfig(BaseModel):
    # The local control panel, served by the LeSysBot service for as long as
    # it runs (`lesysbot run`; `lesysbot manage` serves it ad-hoc when the
    # service is stopped). It is bound to loopback only — the host is
    # deliberately NOT configurable, so it can never be exposed on the LAN.
    # Only the port is.
    port: int = 8700



class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LESYSBOT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Env vars must override the config file. from_yaml() feeds the file's
        # data in as init kwargs, and pydantic-settings ranks init kwargs above
        # env by default — reorder so env wins (sources are deep-merged, so
        # env overrides individual keys without clobbering the rest).
        return (env_settings, init_settings, dotenv_settings, file_secret_settings)

    messaging: MessagingConfig = Field(default_factory=MessagingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    logging: LogConfig = Field(default_factory=LogConfig)
    management: ManagementConfig = Field(default_factory=ManagementConfig)

    # Absolute path of the config.yaml this instance was loaded from (None when
    # running on built-in defaults). Relative `tools/`/`logs/` paths are anchored
    # to its directory so they live next to the config the user edits.
    _config_path: Path | None = PrivateAttr(default=None)

    @property
    def config_path(self) -> Path | None:
        """The active config.yaml itself, or None when running on built-in defaults."""
        return self._config_path

    @property
    def config_dir(self) -> Path | None:
        """Directory the active config.yaml was loaded from, or None for defaults."""
        return self._config_path.parent if self._config_path else None

    @classmethod
    def from_yaml(cls, path: str | Path, *, bundled: bool = False) -> "Settings":
        """Load settings from *path*.

        ``bundled=True`` marks a file that ships **with the package** rather
        than one the user edits (``config/default.yaml``). Its values are used,
        but ``config_dir`` stays ``None`` so relative ``tools_dir``/log paths
        anchor to :func:`app_dir` instead of to the packaged ``config/`` folder
        — otherwise a fresh checkout would resolve ``./tools`` to
        ``<repo>/config/tools`` and find no tools at all.
        """
        data: dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
        missing: list[str] = []
        data = _expand_env(data, missing)
        if missing:
            import logging

            logging.getLogger(__name__).warning(
                "config %s references unset environment variable(s): %s — "
                "the literal ${...} text was kept",
                p, ", ".join(sorted(set(missing))),
            )
        # cls(**data), not model_validate(): only __init__ runs the settings
        # sources (env overrides), which settings_customise_sources ranks
        # above these file-derived kwargs.
        settings = cls(**data)
        if p.exists() and not bundled:
            settings._config_path = p.resolve()
        return settings

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Settings":
        from lesysbot.core.paths import app_dir, user_dir

        base = app_dir()
        # (path, bundled) — bundled files ship with the package and don't
        # anchor relative paths to themselves; see from_yaml().
        candidates: list[tuple[str | Path | None, bool]] = [
            (config_path, False),
            (Path("config.yaml"), False),
            (user_dir() / "config.yaml", False),   # ~/.lesysbot — installed default
            (base / "config.yaml", False),         # next to the .exe in a frozen build
            (Path("config/default.yaml"), True),
            (base / "config" / "default.yaml", True),
        ]
        for candidate, bundled in candidates:
            if candidate and Path(candidate).exists():
                return cls.from_yaml(candidate, bundled=bundled)
        return cls()


def resolve_paths(settings: Settings) -> None:
    """Anchor relative paths to the directory the active config.yaml was loaded
    from, so `tools/`, `logs/` and the state files live next to the config the
    user edits — e.g. ~/.lesysbot for an installed setup. When no config file was
    found (built-in defaults), `config_dir` is None and `anchor()` falls back to
    the app directory: the CWD for a normal run, or the folder containing the
    frozen .exe. Shared by the bot startup and the `lesysbot tools` CLI so both
    resolve the exact same tools dir.
    """
    from lesysbot.core.paths import anchor

    base = settings.config_dir
    settings.mcp.tools_dir = anchor(settings.mcp.tools_dir, base)
    settings.mcp.lock_file = anchor(settings.mcp.lock_file, base)
    if settings.mcp.state_file:
        settings.mcp.state_file = anchor(settings.mcp.state_file, base)
    if settings.logging.file:
        settings.logging.file = anchor(settings.logging.file, base)
    if settings.logging.trace_file:
        settings.logging.trace_file = anchor(settings.logging.trace_file, base)
