from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def app_dir() -> Path:
    """Base directory the app uses to locate `config.yaml`, `tools/` and `logs/`.

    The current working directory — the fallback used when no config file was
    found, so relative defaults like `./tools` resolve where the process runs.
    """
    return Path.cwd()


def user_dir() -> Path:
    """Stable per-user config/data home for an installed LeSysBot.

    Defaults to ``~/.lesysbot`` and can be overridden with the ``LESYSBOT_HOME``
    environment variable. The install wizard writes ``config.yaml`` here (along
    with ``tools/`` and ``logs/``) so there is one well-known place to edit
    settings and restart the service to apply them.
    """
    override = os.environ.get("LESYSBOT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".lesysbot"


def bundled_dir() -> Path:
    """Content that ships *with* LeSysBot: default tools, dashboards, the stack.

    An installed wheel has it at ``lesysbot/_bundled/`` (hatchling copies the
    repo's top-level directories in at build time). A dev checkout has no such
    folder, so it falls back to the repo root beside the package — which is
    where those directories actually live. Both layouts then behave identically,
    and nothing downstream has to know which one it is running from.
    """
    packaged = Path(__file__).resolve().parent.parent / "_bundled"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parent.parent.parent


# The dashboard stack's directory name under the user home.
DASHBOARD_DIRNAME = "dashboard"


def dashboard_dir(base: str | Path | None = None) -> Path:
    """The dashboard stack directory (Prometheus + Grafana + exporters)."""
    root = Path(base) if base is not None else user_dir()
    return root / DASHBOARD_DIRNAME


def installed_dashboards_dir(base: str | Path | None = None) -> Path:
    """Where installed dashboard **packages** live.

    Deliberately nested inside the stack rather than sitting beside it as
    ``~/.lesysbot/dashboards``: distinguishing the stack from its contents by a
    trailing `s` is the kind of thing that reads fine in code and ruins an
    afternoon at a shell prompt.
    """
    return dashboard_dir(base) / "installed"


def generated_dashboards_dir(base: str | Path | None = None) -> Path:
    """Where rendered dashboard JSON is written for Grafana to provision.

    Derived output, rewritten on every render — never edit anything here; edit
    the package under :func:`installed_dashboards_dir` instead.
    """
    return dashboard_dir(base) / "grafana" / "dashboards" / "generated"


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` env file (``#`` comments, quotes stripped).

    Returns ``{}`` when the file is missing. Used for the Grafana connection
    file the setup wizard writes (``grafana.env``); deliberately not a dotenv
    parser — no interpolation, no export keyword, just flat pairs.
    """
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def load_grafana_env() -> dict[str, str]:
    """Load ``~/.lesysbot/grafana.env`` into ``os.environ`` for any key not
    already set, so the Grafana username/password the setup wizard saved reaches
    the ``share_dashboard`` tool and the status screen's Grafana probe. An
    explicit environment variable always wins (``setdefault``). Returns the
    parsed pairs so callers can register the password for log redaction.
    """
    pairs = parse_env_file(user_dir() / "grafana.env")
    for key, val in pairs.items():
        os.environ.setdefault(key, val)
    return pairs


def force_rmtree(path: Path) -> None:
    """``shutil.rmtree`` that clears a read-only bit before giving up.

    A tool package extracted from a zipball can carry modes that make its own
    files or directories undeletable; retry once with write permission restored
    rather than failing the removal.
    """

    def _retry(func, p, _exc) -> None:
        Path(p).chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:  # onerror deprecated in 3.12; same (func, path, info) shape for our use
        shutil.rmtree(path, onerror=_retry)


def anchor(path: str | Path, base: str | Path | None = None) -> str:
    """Resolve a relative path against *base* (default :func:`app_dir`); absolute paths pass through.

    *base* lets the caller anchor relative `tools/`/`logs/` paths to the directory
    the active `config.yaml` was loaded from — e.g. `~/.lesysbot` for an installed
    setup — so they live next to the config the user edits. With `base=None` it
    falls back to :func:`app_dir` (the CWD), so existing relative defaults like
    `./tools` behave exactly as before.
    """
    p = Path(path)
    if p.is_absolute():
        return str(p)
    root = Path(base) if base is not None else app_dir()
    return str(root / p)
