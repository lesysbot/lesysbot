"""Dependency-free management UI server (stdlib ``http.server``).

Serves a single-page control panel plus a small JSON API for LeSysBot's config
and tools. It is bound to **loopback only** and rejects requests whose ``Host``
header isn't localhost (DNS-rebinding protection), so it is never reachable from
the network. There is no auth — the trust boundary is "you have a shell on this
machine", the same as editing ``config.yaml`` by hand.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

from lesysbot.core.config import Settings
from lesysbot.core.paths import user_dir
from lesysbot.core.status import build_registry, detect_grafana, gather_status, probe_health
from lesysbot.webui.page import PAGE

# Host header must resolve to loopback — blocks DNS-rebinding from a web page.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", ""}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, settings, registry):
        super().__init__(addr, handler)
        self.settings = settings
        self.registry = registry
        self.lock = threading.Lock()   # serialize registry mutations/reads


class _Handler(BaseHTTPRequestHandler):
    server_version = "LeSysBotUI"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):  # keep the console clean
        pass

    # -- helpers --------------------------------------------------------------
    def _host_ok(self) -> bool:
        return (self.headers.get("Host", "").split(":")[0]) in _ALLOWED_HOSTS

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
        if path == "/api/status":
            return self._status()
        if path == "/api/tools":
            with self.server.lock:
                return self._send(200, {"tools": self._rows()})
        if path == "/api/config":
            return self._get_config()
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                return self._save_config()
            if path == "/api/tools/toggle":
                return self._toggle()
            if path == "/api/tools/install":
                return self._install()
            if path == "/api/tools/remove":
                return self._remove()
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
        st["grafana"] = detect_grafana()
        self._send(200, st)

    def _rows(self):
        rows = self.server.registry.tool_status()
        for r in rows:
            src = r.pop("source", None)
            r["source_kind"] = src.get("kind") if src else None
        return rows

    def _get_config(self):
        s = self.server.settings
        path = Path(s.config_path) if s.config_path else (user_dir() / "config.yaml")
        if path.exists():
            text = path.read_text()
        else:
            text = yaml.safe_dump(s.model_dump(mode="json", exclude_none=True),
                                  sort_keys=False)
        self._send(200, {"yaml": text, "path": str(path), "exists": path.exists()})

    def _save_config(self):
        text = self._body().get("yaml", "")
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            return self._send(400, {"ok": False, "error": f"YAML parse error: {e}"})
        if not isinstance(data, dict):
            return self._send(400, {"ok": False, "error": "config must be a mapping"})
        try:
            Settings(**data)                     # validate against the schema
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"Invalid config: {e}"})
        s = self.server.settings
        path = Path(s.config_path) if s.config_path else (user_dir() / "config.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self._send(200, {"ok": True, "path": str(path),
                         "note": "Saved. Restart the bot to apply (tool enable/disable is live)."})

    def _toggle(self):
        body = self._body()
        name, enabled = body.get("name"), bool(body.get("enabled"))
        with self.server.lock:
            known = {t["name"] for t in self.server.registry.tool_status()}
            if name not in known:
                return self._send(404, {"ok": False, "error": "unknown tool"})
            self.server.registry.set_enabled(name, enabled)   # persists to state_file
        self._send(200, {"ok": True, "name": name, "enabled": enabled})

    def _install(self):
        source = (self._body().get("source") or "").strip()
        if not source:
            return self._send(400, {"ok": False, "error": "missing source"})
        from lesysbot.install.manager import ToolInstaller
        from lesysbot.install.spec import parse_source
        s = self.server.settings
        try:
            src = parse_source(source)
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"bad source: {e}"})
        installer = ToolInstaller(Path(s.mcp.tools_dir), Path(s.mcp.lock_file))
        names = installer.install(src, yes=True)     # yes=True: no interactive prompt
        with self.server.lock:
            self.server.registry.reload(s.mcp.tools_dir)
        self._send(200, {"ok": True, "installed": names})

    def _remove(self):
        name = self._body().get("name")
        s = self.server.settings
        with self.server.lock:
            reg = self.server.registry
            src = reg.tool_source(name)
            if src is None:
                return self._send(400, {"ok": False,
                                        "error": "tool has no removable source"})
            reg.remove_tool(name)
            try:
                from lesysbot.install.lockfile import drop_entries
                drop_entries(Path(s.mcp.lock_file), src.get("tools", []))
            except Exception:
                pass
        self._send(200, {"ok": True, "removed": name})


def serve(settings: Settings, *, registry=None, port: int | None = None,
          open_browser: bool = False) -> None:
    """Start the management UI on loopback and serve until interrupted."""
    import webbrowser

    want = port or settings.webui.port
    reg = registry if registry is not None else build_registry(settings)

    httpd = None
    for candidate in range(want, want + 20):     # step past a busy port
        try:
            httpd = _Server(("127.0.0.1", candidate), _Handler, settings, reg)
            break
        except OSError:
            continue
    if httpd is None:
        raise OSError(f"No free port in {want}..{want + 19} for the management UI.")

    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"\n  \033[1mManagement UI:\033[0m {url}   (localhost only · Ctrl-C to stop)\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nManagement UI stopped.")
    finally:
        httpd.shutdown()
        httpd.server_close()
