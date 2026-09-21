from __future__ import annotations

from pathlib import Path

from lesysbot.core.config import Settings, resolve_paths
from lesysbot.core.paths import load_grafana_env, parse_env_file


def test_parse_env_file(tmp_path: Path) -> None:
    p = tmp_path / "grafana.env"
    p.write_text('# comment\nLESYSBOT_GRAFANA_USER=bob\nLESYSBOT_GRAFANA_PASSWORD="p w"\nbad line\n')
    pairs = parse_env_file(p)
    assert pairs == {"LESYSBOT_GRAFANA_USER": "bob", "LESYSBOT_GRAFANA_PASSWORD": "p w"}
    assert parse_env_file(tmp_path / "missing.env") == {}  # missing → {}


def test_load_grafana_env_sets_env_and_respects_override(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "grafana.env").write_text(
        "LESYSBOT_GRAFANA_URL=http://gf:3000\n"
        "LESYSBOT_GRAFANA_USER=bob\n"
        "LESYSBOT_GRAFANA_PASSWORD=filepw\n"
    )
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.delenv("LESYSBOT_GRAFANA_URL", raising=False)
    monkeypatch.delenv("LESYSBOT_GRAFANA_USER", raising=False)
    monkeypatch.setenv("LESYSBOT_GRAFANA_PASSWORD", "already-set")  # explicit env wins
    load_grafana_env()
    import os

    assert os.environ["LESYSBOT_GRAFANA_URL"] == "http://gf:3000"     # from file
    assert os.environ["LESYSBOT_GRAFANA_USER"] == "bob"               # from file
    assert os.environ["LESYSBOT_GRAFANA_PASSWORD"] == "already-set"   # not overwritten


def test_defaults() -> None:
    s = Settings()
    assert s.messaging.provider == "cli"
    assert s.llm.base_url == "http://localhost:11434/v1"
    assert s.llm.model == "qwen3.5:4b"


def test_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "llm:\n"
        "  model: qwen3.5\n"
        "  base_url: http://localhost:8000/v1\n"
        "messaging:\n"
        "  provider: telegram\n"
    )
    s = Settings.from_yaml(cfg)
    assert s.llm.model == "qwen3.5"
    assert s.llm.base_url == "http://localhost:8000/v1"
    assert s.messaging.provider == "telegram"
    # unset fields fall back to defaults
    assert s.llm.temperature == 0.7


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LESYSBOT_LLM__MODEL", "from-env")
    monkeypatch.setenv("LESYSBOT_AGENT__MAX_HISTORY", "123")
    s = Settings()
    assert s.llm.model == "from-env"
    assert s.agent.max_history == 123


def test_missing_yaml_uses_defaults(tmp_path: Path) -> None:
    s = Settings.from_yaml(tmp_path / "does-not-exist.yaml")
    assert s.llm.model == "qwen3.5:4b"


def test_bundled_default_does_not_anchor_paths_to_itself(
    tmp_path: Path, monkeypatch
) -> None:
    """A fresh checkout must find `<repo>/tools`, not `<repo>/config/tools`.

    `config/default.yaml` ships with the package rather than being a config the
    user edits, so it supplies values but leaves `config_dir` None — relative
    paths then anchor to app_dir() (the CWD) like the built-in defaults do.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.yaml").write_text("llm:\n  model: bundled\n")
    (tmp_path / "tools").mkdir()
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / "no-home"))
    monkeypatch.chdir(tmp_path)

    s = Settings.load()
    assert s.llm.model == "bundled"          # values still come from the file
    assert s.config_dir is None              # but it is not a user config dir

    resolve_paths(s)
    assert Path(s.mcp.tools_dir) == tmp_path / "tools"
    assert Path(s.mcp.tools_dir).is_dir()


def test_user_config_still_anchors_next_to_itself(tmp_path: Path, monkeypatch) -> None:
    """A real config.yaml keeps winning over the bundled defaults, and its
    directory is what relative paths resolve against."""
    home = tmp_path / "home"
    (home / "tools").mkdir(parents=True)
    (home / "config.yaml").write_text("llm:\n  model: mine\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.yaml").write_text("llm:\n  model: bundled\n")
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.chdir(tmp_path)

    s = Settings.load()
    assert s.llm.model == "mine"
    assert s.config_dir == home.resolve()

    resolve_paths(s)
    assert Path(s.mcp.tools_dir) == home / "tools"


def test_config_dir_tracks_source(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  model: qwen3.5\n")
    s = Settings.from_yaml(cfg)
    assert s.config_dir == tmp_path.resolve()
    # Built-in defaults have no source file.
    assert Settings().config_dir is None


def test_resolve_paths_anchors_to_config_dir(tmp_path: Path) -> None:
    # Relative tools/log/state paths anchor next to the loaded config — the
    # the `lesysbot` CLI and the bot must resolve the exact same locations.
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  model: qwen3.5\n")
    s = Settings.from_yaml(cfg)
    resolve_paths(s)
    assert s.mcp.tools_dir == str(tmp_path / "tools")
    assert s.mcp.lock_file == str(tmp_path / "lesysbot.lock.json")
    assert s.mcp.state_file == str(tmp_path / "tool_state.json")


def test_load_picks_up_user_dir(tmp_path: Path, monkeypatch) -> None:
    # LESYSBOT_HOME points user_dir() at a temp dir holding config.yaml; with no
    # cwd config.yaml and no explicit -c, load() should resolve it from there.
    home = tmp_path / ".lesysbot"
    home.mkdir()
    (home / "config.yaml").write_text("llm:\n  model: from-user-dir\n")
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.chdir(tmp_path)  # tmp_path has no config.yaml of its own

    s = Settings.load()
    assert s.llm.model == "from-user-dir"
    assert s.config_dir == home.resolve()


def test_env_var_expansion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LESYSBOT_TEST_TOKEN", "123:abc")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("messaging:\n  telegram:\n    token: ${LESYSBOT_TEST_TOKEN}\n")
    s = Settings.from_yaml(cfg)
    assert s.messaging.telegram.token == "123:abc"


def test_env_expansion_inside_larger_string(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LESYSBOT_TEST_HOSTNAME", "myhost")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  base_url: http://${LESYSBOT_TEST_HOSTNAME}:11434/v1\n")
    s = Settings.from_yaml(cfg)
    assert s.llm.base_url == "http://myhost:11434/v1"


def test_unset_env_var_kept_literal_with_warning(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.delenv("LESYSBOT_TEST_UNSET", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  api_key: ${LESYSBOT_TEST_UNSET}\n")
    with caplog.at_level("WARNING"):
        s = Settings.from_yaml(cfg)
    assert s.llm.api_key == "${LESYSBOT_TEST_UNSET}"
    assert "LESYSBOT_TEST_UNSET" in caplog.text


def test_env_overrides_yaml_file(tmp_path: Path, monkeypatch) -> None:
    """LESYSBOT_ env vars must beat the config file — from_yaml goes through
    __init__ so the env source applies, ranked above the file's data."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  model: from-file\n  temperature: 0.5\n")
    monkeypatch.setenv("LESYSBOT_LLM__MODEL", "from-env")
    s = Settings.from_yaml(cfg)
    assert s.llm.model == "from-env"
    # sibling keys from the file survive the env deep-merge
    assert s.llm.temperature == 0.5


def test_shipped_default_yaml_has_no_key_settings_ignores() -> None:
    """Every top-level section in `config/default.yaml` must be a real field.

    `Settings` is `extra="ignore"`, which it has to be (an old config must not
    stop the bot booting) — but that also means a section renamed in the code
    and not in the shipped YAML goes on being parsed and silently discarded.
    That is exactly how `webui:` outlived the rename to `management:`: the key
    still documented a port nobody could change, because setting it did
    nothing at all. This pins the two together.
    """
    import yaml

    from lesysbot.core.config import Settings

    shipped = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    data = yaml.safe_load(shipped.read_text()) or {}
    unknown = set(data) - set(Settings.model_fields)
    assert not unknown, (
        f"{shipped.name} has section(s) Settings would silently ignore: "
        f"{sorted(unknown)} — rename them, or add the field."
    )
