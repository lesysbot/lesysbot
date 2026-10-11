"""Dependency-free control-panel server (stdlib ``http.server``).

Serves a single-page control panel plus a small JSON API for LeSysBot's config
and tools. It is bound to **loopback only** and rejects requests whose ``Host``
header isn't localhost (DNS-rebinding protection), so it is never reachable from
the network. There is no auth — the trust boundary is "you have a shell on this
machine", the same as editing ``config.yaml`` by hand.

Two ways to run it: :func:`serve_background` (what the always-on service uses —
a daemon thread beside the bot, so the panel answers whenever LeSysBot runs) and
:func:`serve` (foreground, for ``lesysbot manage`` when no service is around).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from rich.console import Console

from lesysbot.cli.context import CLIContext

from lesysbot.core.config import Settings
from lesysbot.core.paths import user_dir
from lesysbot.core.status import build_registry, detect_grafana, gather_status, probe_health
from lesysbot.management import configedit, messaging
from lesysbot.management.jobs import JobRegistry
from lesysbot.management.page import PAGE

# Host header must resolve to loopback — blocks DNS-rebinding from a web page.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", ""}

# Answered by /api/ping so a probe can tell *our* panel from whatever else may
# have taken the port (see core/status.detect_panel).
PING = {"ok": True, "service": "lesysbot-management"}


SERVICE = "lesysbot"


def write_config_text(path: Path, text: str) -> None:
    """Replace config.yaml atomically — the bot may read it at any moment.

    The file holds bot tokens, so a new one is created owner-only; an existing
    one keeps whatever mode its owner gave it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def service_info(runner=subprocess.run) -> dict:
    """Is the ``systemd --user`` unit installed, so the panel can restart it?"""
    if os.environ.get("LESYSBOT_SKIP_SERVICE") or not shutil.which("systemctl"):
        return {"installed": False}
    try:
        r = runner(["systemctl", "--user", "cat", SERVICE], capture_output=True, timeout=5)
    except Exception:
        return {"installed": False}
    return {"installed": r.returncode == 0}


def restart_service(runner=subprocess.run) -> dict:
    """Queue a restart of the service and return at once.

    ``--no-block`` matters: the panel usually lives *inside* that service, so
    waiting for the restart would mean waiting for our own death.
    """
    if not service_info(runner)["installed"]:
        return {"ok": False, "error": "No LeSysBot service is installed here — restart "
                                      "LeSysBot however you started it."}
    r = runner(["systemctl", "--user", "--no-block", "restart", SERVICE],
               capture_output=True, timeout=10)
    if r.returncode != 0:
        err = (r.stderr or b"").decode(errors="replace").strip()
        return {"ok": False, "error": err or "systemctl restart failed"}
    return {"ok": True, "note": "Restarting… the panel will be back in a few seconds."}


class CLIContextProxy:
    """A CLIContext with the console swapped for a job's output sink.

    The artifact verbs are written against CLIContext and print through it, so
    reusing them from the panel is a matter of pointing that console somewhere
    else — rather than reimplementing update/remove a second time and letting
    the two drift.
    """

    def __init__(self, ctx, console) -> None:
        self._ctx = ctx
        self.console = console

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    def error(self, message: str) -> int:
        self.console.print(f"Error: {message}")
        return 1


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR rebinds a port stuck in TIME_WAIT, so a restarted service
    # isn't blocked by its own dead socket. On Linux it still refuses a port
    # that is actively bound, which is what `_bind` relies on for the
    # single-panel guarantee (a second copy must fail fast).
    allow_reuse_address = True

    def __init__(self, addr, handler, settings, registry):
        super().__init__(addr, handler)
        self.settings = settings
        self.registry = registry
        self.lock = threading.Lock()   # serialize registry mutations/reads
        self.jobs = JobRegistry()
        # The same object the CLI verbs take, so the panel and the terminal
        # resolve identical paths and share one implementation of each verb.
        self.ctx = CLIContext(settings, Console(quiet=True))


class _Handler(BaseHTTPRequestHandler):
    server_version = "LeSysBotUI"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):  # keep the console clean
        pass

    # -- helpers --------------------------------------------------------------
    def _host_ok(self) -> bool:
        return (self.headers.get("Host", "").split(":")[0]) in _ALLOWED_HOSTS

    def _write_ok(self) -> bool:
        """Is this POST from the panel itself, not another site in the browser?

        The Host check stops DNS rebinding, not cross-site requests: any page
        can POST to ``http://127.0.0.1:8700`` and the Host still reads
        127.0.0.1. Such a "simple" request can't set ``Content-Type:
        application/json`` without a CORS preflight, which this server never
        answers — so requiring it, plus a loopback Origin when one is sent,
        keeps a web page from rewriting the bot token or installing a tool.
        """
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True                  # not a browser (curl, tests)
        return (urlparse(origin).hostname or "") in _ALLOWED_HOSTS - {""}

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, bytes):
            data = body
        elif ctype == "application/json":
            data = json.dumps(body).encode()
        else:
            data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # -- routing --------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html")
        if path == "/api/ping":
            # Deliberately touches nothing (no registry, no lock): it exists so a
            # liveness probe stays cheap enough to run on every status screen.
            return self._send(200, PING)
        if path == "/api/status":
            return self._status()
        if path == "/api/tools":
            with self.server.lock:
                return self._send(200, {"tools": self._rows()})
        if path == "/api/config":
            return self._get_config()
        if path == "/api/messaging":
            return self._get_messaging()
        if path == "/api/artifacts":
            return self._artifacts()
        if path == "/api/prereq":
            return self._prereq()
        if path == "/api/jobs":
            return self._send(200, {"jobs": self.server.jobs.list()})
        if path.startswith("/api/jobs/"):
            return self._job(path.rsplit("/", 1)[-1])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        if not self._write_ok():
            return self._send(403, {"error": "cross-site request refused"})
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                return self._save_config()
            if path == "/api/tools/toggle":
                return self._toggle()
            if path in ("/api/tools/install", "/api/artifacts/install"):
                return self._install()
            if path in ("/api/tools/remove", "/api/artifacts/remove"):
                return self._remove()
            if path == "/api/artifacts/update":
                return self._update()
            if path == "/api/messaging":
                return self._save_messaging()
            if path == "/api/messaging/test":
                return self._test_token()
            if path == "/api/service/restart":
                return self._restart()
        except Exception as e:  # never leak a traceback to the browser
            return self._send(500, {"ok": False, "error": str(e)})
        return self._send(404, {"error": "not found"})

    # -- endpoints ------------------------------------------------------------
    def _status(self):
        with self.server.lock:
            st = asyncio.run(gather_status(self.server.settings, self.server.registry,
                                           check_health=False))
        # LLM health + Grafana probe hit the network — do them outside the lock.
        try:
            st["health"] = asyncio.run(probe_health(self.server.settings.llm))
        except Exception as e:
            st["health"] = {"ok": False, "error": str(e)}
        st["grafana"] = self._grafana()
        # We are the panel — no need to probe ourselves to answer "is it up?".
        port = self.server.server_address[1]
        st["panel"] = {"url": f"http://127.0.0.1:{port}", "port": port, "running": True}
        self._send(200, st)

    def _rows(self):
        rows = self.server.registry.tool_status()
        for r in rows:
            src = r.pop("source", None)
            r["source_kind"] = src.get("kind") if src else None
        return rows

    def _config_file(self) -> Path:
        s = self.server.settings
        return Path(s.config_path) if s.config_path else (user_dir() / "config.yaml")

    def _config_text(self) -> str:
        """config.yaml as written (``${VAR}`` unexpanded), or the defaults."""
        path = self._config_file()
        if path.exists():
            return path.read_text()
        return yaml.safe_dump(self.server.settings.model_dump(mode="json", exclude_none=True),
                              sort_keys=False)

    def _write_config(self, text: str) -> Path:
        path = self._config_file()
        write_config_text(path, text)
        return path

    def _get_config(self):
        # Tokens and keys never reach the browser: they go out as <hidden> and
        # are put back on save (configedit.unmask).
        path = self._config_file()
        self._send(200, {"yaml": configedit.mask(self._config_text()), "path": str(path),
                         "exists": path.exists(), "hidden": configedit.HIDDEN})

    def _save_config(self):
        text = self._body().get("yaml", "")
        try:
            text, data = configedit.unmask(text, self._config_text())
        except yaml.YAMLError as e:
            return self._send(400, {"ok": False, "error": f"YAML parse error: {e}"})
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        try:
            Settings(**data)                     # validate against the schema
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"Invalid config: {e}"})
        path = self._write_config(text)
        self._send(200, {"ok": True, "path": str(path),
                         "note": "Saved. Restart the LeSysBot service to apply "
                                 "(tool enable/disable is live)."})

    def _get_messaging(self):
        path = self._config_file()
        try:
            view = messaging.view(self._config_text(), self.server.settings)
        except (yaml.YAMLError, ValueError) as e:
            return self._send(400, {"ok": False, "error": f"config.yaml can't be read: {e}"})
        view.update(path=str(path), exists=path.exists(), service=service_info())
        self._send(200, view)

    def _save_messaging(self):
        try:
            text, _ = messaging.apply(self._config_text(), self._body())
        except yaml.YAMLError as e:
            return self._send(400, {"ok": False, "error": f"config.yaml can't be read: {e}"})
        except Exception as e:                   # ValueError, pydantic ValidationError
            return self._send(400, {"ok": False, "error": str(e)})
        path = self._write_config(text)
        self._send(200, {"ok": True, "path": str(path),
                         "note": "Saved. Restart the service to apply."})

    def _test_token(self):
        body = self._body()
        provider = body.get("provider")
        token = (body.get("token") or "").strip()
        if not token:                            # nothing typed → test the saved one
            token = configedit.get(configedit.load(self._config_text()),
                                   ("messaging", provider, "token")) or ""
        self._send(200, messaging.check_token(provider, token))

    def _restart(self):
        result = restart_service()
        self._send(202 if result["ok"] else 400, result)

    def _toggle(self):
        body = self._body()
        name, enabled = body.get("name"), bool(body.get("enabled"))
        with self.server.lock:
            known = {t["name"] for t in self.server.registry.tool_status()}
            if name not in known:
                return self._send(404, {"ok": False, "error": "unknown tool"})
            self.server.registry.set_enabled(name, enabled)   # persists to state_file
        self._send(200, {"ok": True, "name": name, "enabled": enabled})

    def _artifacts(self):
        from lesysbot.cli import artifacts as artifact_cli

        with self.server.lock:
            rows = artifact_cli._rows(self.server.ctx)
        for row in rows:
            row.pop("source", None)          # a Path isn't JSON-serialisable
        self._send(200, {"artifacts": rows})

    def _grafana(self):
        """Grafana, plus a link straight to the System Overview dashboard.

        Grafana's root URL lands on its home page, one click short of anything
        useful, so the panel links ``/d/<uid>`` of a provisioned dashboard.
        """
        from lesysbot.core.grafana import home_dashboard_url

        gf = detect_grafana()
        if gf and gf["reachable"]:
            gf["dashboard_url"] = home_dashboard_url(gf["url"], self.server.ctx.settings.config_dir)
        return gf

    def _prereq(self):
        from lesysbot.cli.doctor import _as_dict, _gather

        name = parse_qs(urlparse(self.path).query).get("name", [None])[0]
        reports = _gather(self.server.ctx, name)
        self._send(200, {"reports": [_as_dict(r) for r in reports]})

    def _job(self, job_id: str):
        job = self.server.jobs.get(job_id)
        if job is None:
            return self._send(404, {"error": "unknown job"})
        self._send(200, job.as_dict())

    # -- mutations ------------------------------------------------------------
    def _install(self):
        """Start an install as a background job; the browser polls for progress.

        Doing this inline would hold the request open for a zipball download and
        a pip run — long enough that a slow network is indistinguishable from a
        hung panel.
        """
        from lesysbot.artifacts.spec import parse_source

        body = self._body()
        source = (body.get("source") or "").strip()
        if not source:
            return self._send(400, {"ok": False, "error": "missing source"})

        ctx = self.server.ctx
        # Same rule as `lesysbot install`: a path on this machine wins, else a
        # GitHub link. The panel runs as the user on loopback, so a path here is
        # the same authority as typing the command — and a panel that rejected
        # what the terminal accepts would be its own bug report.
        local = Path(source).expanduser()
        if not local.exists():
            try:
                src = parse_source(source)
            except Exception as e:
                return self._send(400, {"ok": False, "error": f"bad source: {e}"})
        else:
            src = None

        server = self.server

        def work(console):
            installer = ctx.installer(console=console)
            deps = body.get("deps", True)
            result = (installer.install(src, yes=True, install_deps=deps)
                      if src is not None
                      else installer.install_path(local, yes=True, install_deps=deps))
            with server.lock:
                server.registry.reload(ctx.settings.mcp.tools_dir)
            return {"installed": result.names}

        job = server.jobs.start("install", f"Installing {source}", work)
        self._send(202, {"ok": True, "job": job.id})

    def _update(self):
        name = (self._body().get("name") or "").strip()
        ctx = self.server.ctx
        server = self.server

        def work(console):
            import argparse

            from lesysbot.cli import artifacts as artifact_cli

            local = CLIContextProxy(ctx, console)
            args = argparse.Namespace(command="update", names=[name] if name else [],
                                      check=False, yes=True)
            code = artifact_cli._update(local, args)
            with server.lock:
                server.registry.reload(ctx.settings.mcp.tools_dir)
            return {"exit_code": code}

        job = server.jobs.start("update", f"Updating {name or 'everything'}", work)
        self._send(202, {"ok": True, "job": job.id})

    def _remove(self):
        """Delete an installed tool package, by name."""
        import argparse

        from lesysbot.cli import artifacts as artifact_cli

        name = self._body().get("name")
        ctx = self.server.ctx
        with self.server.lock:
            args = argparse.Namespace(command="remove", name=name, yes=True)
            code = artifact_cli._remove(ctx, args)
            if code == 0:
                self.server.registry.reload(ctx.settings.mcp.tools_dir)
        if code != 0:
            return self._send(400, {"ok": False, "error": f"could not remove {name!r}"})
        self._send(200, {"ok": True, "removed": name})


def _bind(settings: Settings, registry, want: int, *, step: bool) -> _Server | None:
    """Bind the panel on loopback. ``step`` walks past a busy port (foreground
    use); the service binds its configured port exactly, so the panel always
    lives at the one URL people bookmark — and a second copy fails fast instead
    of quietly serving a duplicate somewhere else."""
    for candidate in range(want, want + 20 if step else want + 1):
        try:
            return _Server(("127.0.0.1", candidate), _Handler, settings, registry)
        except OSError:
            continue
    return None


@dataclass
class BackgroundUI:
    """A control panel running in a daemon thread beside the bot."""

    server: _Server
    thread: threading.Thread
    url: str

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def serve_background(settings: Settings, *, registry=None,
                     port: int | None = None) -> BackgroundUI | None:
    """Serve the panel from a daemon thread and return immediately.

    Used by ``lesysbot run`` so the control panel is online for as long as the
    service is. Returns ``None`` (never raises) when the port is unavailable:
    the panel is a companion to the bot, so a busy port must not take the whole
    service down — usually it means a second copy is already serving it.
    """
    reg = registry if registry is not None else build_registry(settings)
    httpd = _bind(settings, reg, port or settings.management.port, step=False)
    if httpd is None:
        return None
    thread = threading.Thread(target=httpd.serve_forever, name="lesysbot-management",
                              daemon=True)
    thread.start()
    return BackgroundUI(httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}")


def serve(settings: Settings, *, registry=None, port: int | None = None,
          open_browser: bool = False) -> None:
    """Start the control panel on loopback and serve until interrupted."""
    import webbrowser

    want = port or settings.management.port
    reg = registry if registry is not None else build_registry(settings)

    httpd = _bind(settings, reg, want, step=True)
    if httpd is None:
        raise OSError(f"No free port in {want}..{want + 19} for the control panel.")

    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"\n  \033[1mControl panel:\033[0m {url}   (localhost only · Ctrl-C to stop)\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nControl panel stopped.")
    finally:
        httpd.shutdown()
        httpd.server_close()
