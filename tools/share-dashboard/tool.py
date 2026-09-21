"""Share the LeSysBot Grafana dashboard as a public snapshot on snapshots.raintank.io.

Text the bot **"share me the dashboard"** and it publishes a point-in-time
snapshot — the current graphs baked in as data — *through Grafana* to its public
snapshot server (raintank), returns the link, and lets you list and delete your
shares (Grafana's own snapshot registry is the source of truth; a local record
keeps each raintank delete key so orphans stay deletable), with a sharing
expiration of your choice.

Needs the dashboard stack running (see ``dashboard/README.md``). Everything is
configured by environment variables, all optional:

  LESYSBOT_GRAFANA_URL       Grafana base URL           (default http://localhost:3000)
  LESYSBOT_GRAFANA_USER      basic-auth user            (default admin)
  LESYSBOT_GRAFANA_PASSWORD  basic-auth password        (default admin)
  LESYSBOT_GRAFANA_TOKEN     Bearer token (wins over user/password if set)
  LESYSBOT_GRAFANA_DS_UID    Prometheus datasource uid  (default "prometheus")
  LESYSBOT_DASHBOARD_UID     dashboard to share         (default: first tagged "lesysbot")
  LESYSBOT_RAINTANK_URL      snapshot server            (default https://snapshots.raintank.io)
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from lesysbot.mcp import tool

# Named sharing-expiration presets → seconds (0 = never expires).
EXPIRATIONS = {
    "1h": 3600, "6h": 21600, "12h": 43200,
    "1d": 86400, "7d": 604800, "30d": 2592000,
    "never": 0,
}

# Snapshot data window: the last hour, sampled every 30s.
WINDOW_MIN = 60
STEP_SEC = 30


class _StackDown(Exception):
    """Grafana (the dashboard stack) is unreachable."""


# --------------------------------------------------------------------------- config
# Where Grafana usually lives. The tool probes these and uses the first that
# actually answers as Grafana — so it "just works" whether the stack is on the
# default 3000 or was bumped to 3001 (e.g. when 3000 was already taken), without
# any configuration.
_PORTS = ["3000", "3001"]
_HOSTS = ["localhost", "127.0.0.1"]


def _home() -> Path:
    return Path(os.environ.get("LESYSBOT_HOME", str(Path.home() / ".lesysbot")))


def _grafana_port():
    """GRAFANA_PORT from the bundled stack's .env — the one place the port is set."""
    try:
        text = (_home() / "dashboard" / ".env").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, val = line.strip().partition("=")
        if key.strip() == "GRAFANA_PORT" and val.strip().isdigit():
            return val.strip()
    return None


def _candidates() -> list:
    ports = _PORTS if (p := _grafana_port()) is None else [p, *_PORTS]
    return list(dict.fromkeys(f"http://{h}:{port}" for port in ports for h in _HOSTS))


def _is_grafana(url, timeout=1.5) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=timeout) as r:
            d = json.load(r)
        return isinstance(d, dict) and ("database" in d or "version" in d)
    except Exception:
        return False


def _resolve_grafana(cfg) -> str:
    """The Grafana URL to use: an explicit env override wins *if it answers there*.

    The override is verified rather than trusted, because a saved
    LESYSBOT_GRAFANA_URL goes stale the moment the stack moves off 3000 (when
    something else owns that port) — and posting snapshots to whatever else sits
    on 3000 fails confusingly. An override that doesn't answer as Grafana falls
    through to probing the local ports.
    """
    if cfg["grafana_explicit"] and _is_grafana(cfg["grafana"]):
        return cfg["grafana"]
    for url in _candidates():
        if _is_grafana(url):
            return url
    return cfg["grafana"]   # none answered — keep the default for a sensible error


def _cfg():
    env = os.environ.get("LESYSBOT_GRAFANA_URL", "").rstrip("/")
    return {
        "grafana": env or "http://localhost:3000",
        "grafana_explicit": bool(env),
        "user": os.environ.get("LESYSBOT_GRAFANA_USER", "admin"),
        "password": os.environ.get("LESYSBOT_GRAFANA_PASSWORD", "admin"),
        "token": os.environ.get("LESYSBOT_GRAFANA_TOKEN", ""),
        "ds": os.environ.get("LESYSBOT_GRAFANA_DS_UID", "prometheus"),
        "uid": os.environ.get("LESYSBOT_DASHBOARD_UID", ""),
        "raintank": os.environ.get("LESYSBOT_RAINTANK_URL", "https://snapshots.raintank.io").rstrip("/"),
    }


def _state_file() -> Path:
    return _home() / "dashboard_snapshots.json"


# --------------------------------------------------------------------------- http
def _auth(cfg):
    if cfg["token"]:
        return {"Authorization": f"Bearer {cfg['token']}"}
    raw = f"{cfg['user']}:{cfg['password']}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(url, body, headers=None, timeout=45):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _delete(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {}, method="DELETE")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def _grafana(cfg, path):
    try:
        return _get(cfg["grafana"] + path, headers=_auth(cfg))
    except urllib.error.URLError as e:
        raise _StackDown(str(e)) from e


def _grafana_snapshots(cfg):
    """The snapshots Grafana itself holds — its ``/dashboard/snapshots`` page.

    Now that we publish *through* Grafana (external snapshots), Grafana is the
    registry, so this — not the local file — is the source of truth for listing
    and deleting. External snapshots expose the public raintank link as
    ``externalUrl``; internal ones only have a local Grafana view URL."""
    out = []
    for s in _grafana(cfg, "/api/dashboard/snapshots"):   # _StackDown if unreachable
        key = s.get("key", "")
        out.append({
            "key": key,
            "name": s.get("name") or "snapshot",
            "url": s.get("externalUrl") or f'{cfg["grafana"]}/dashboard/snapshot/{key}',
            "external": bool(s.get("external")),
            "expires": s.get("expires", ""),
        })
    return out


# --------------------------------------------------------------------------- snapshot build
def _subst(expr, step):
    """Resolve the Grafana template tokens our dashboards use into concrete values."""
    return (expr
            .replace("$__rate_interval", "1m")
            .replace("$__interval", f"{step}s")
            .replace("$__range", f"{WINDOW_MIN}m")
            .replace("$instance", ".+"))


_LEG = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _legend(fmt, labels):
    if fmt:
        return _LEG.sub(lambda m: labels.get(m.group(1), ""), fmt).strip()
    name = labels.get("__name__", "")
    rest = {k: v for k, v in labels.items() if k != "__name__"}
    return f"{name} {rest}".strip() if name else (str(rest) if rest else "series")


def _num(v):
    try:
        f = float(v)
        return None if f != f or f in (float("inf"), float("-inf")) else f
    except (TypeError, ValueError):
        return None


def _query_range(cfg, expr, start, end, step):
    q = urlencode({"query": expr, "start": start, "end": end, "step": f"{step}s"})
    url = f'{cfg["grafana"]}/api/datasources/proxy/uid/{cfg["ds"]}/api/v1/query_range?{q}'
    try:
        d = _get(url, headers=_auth(cfg))
    except urllib.error.HTTPError:
        return []
    return d.get("data", {}).get("result", []) if d.get("status") == "success" else []


def _target_snapshot(cfg, expr, fmt, refid, start, end, step):
    """One panel target's baked data as a `snapshot` list — an entry per
    returned series, in Grafana's modern data-frame form (schema + values).

    This is the format Grafana 11 (and the raintank renderer) actually reads.
    The older top-level ``panel.snapshotData`` is ignored there, so a snapshot
    that carries data only in ``snapshotData`` renders as empty panels."""
    entries = []
    resolved = _subst(expr, step)
    first = True
    for s in _query_range(cfg, resolved, start, end, step):
        labels = s.get("metric", {})
        name = _legend(fmt, labels) or expr
        times, vals = [], []
        for ts, val in s.get("values", []):
            times.append(int(float(ts) * 1000))
            vals.append(_num(val))
        meta = {"custom": {"resultType": "matrix"},
                "preferredVisualisationType": "graph",
                "type": "timeseries-multi", "typeVersion": [0, 1]}
        if first:                       # Grafana keeps the query text on the first frame
            meta["executedQueryString"] = f"Expr: {resolved}\nStep: {step}s"
            first = False
        entries.append({
            "data": {"values": [times, vals]},
            "schema": {
                "refId": refid,
                "meta": meta,
                "fields": [
                    {"name": "Time", "type": "time",
                     "typeInfo": {"frame": "time.Time"},
                     "config": {"interval": step * 1000}},
                    {"name": "Value", "type": "number", "labels": labels,
                     "typeInfo": {"frame": "float64"},
                     "config": {"displayNameFromDS": name}},
                ],
            },
        })
    return entries


def _bake(cfg, model):
    """Turn every panel's live queries into baked snapshot targets, so the
    public copy renders without reaching back to your Prometheus. Each target
    becomes a ``queryType: "snapshot"`` target carrying the data (see
    ``_target_snapshot``); Grafana then publishes the model externally."""
    end = int(time.time())
    start = end - WINDOW_MIN * 60
    for p in model.get("panels", []):
        if p.get("type") == "row":
            continue
        targets = []
        for t in p.get("targets", []):
            refid = t.get("refId", "A")
            entries = (_target_snapshot(cfg, t["expr"], t.get("legendFormat", ""),
                                        refid, start, end, STEP_SEC)
                       if t.get("expr") else [])
            targets.append({
                "datasource": {"name": "grafana", "uid": "grafana"},
                "queryType": "snapshot",
                "refId": refid,
                "snapshot": entries,
            })
        p["targets"] = targets
        p["datasource"] = {"name": "grafana", "uid": "grafana"}
    model.pop("id", None)
    model["time"] = {"from": str(start * 1000), "to": str(end * 1000)}
    model["snapshot"] = {"timestamp": datetime.now(timezone.utc).isoformat()}
    return model


# --------------------------------------------------------------------------- state
def _load():
    f = _state_file()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text()).get("snapshots", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save(recs):
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"snapshots": recs}, indent=2))


def _prune(recs):
    now = int(time.time())
    return [r for r in recs if r.get("expires_at") is None or r["expires_at"] > now]


def _dur(sec):
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec >= n:
            return f"{sec // n}{unit}"
    return f"{max(sec, 0)}s"


def _expires_text(iso):
    """Human 'expires in …' for Grafana's ISO expiry (zero-time = never)."""
    if not iso or iso.startswith("0001-01-01"):
        return "never expires"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    rem = int(dt.timestamp() - time.time())
    return f"expires in {_dur(rem)}" if rem > 0 else "expired"


def _local_only_items(local, skip=()):
    """Unexpired local records not already covered by Grafana — the orphans
    Grafana has pruned (still live on raintank until they expire), or the whole
    list when Grafana is unreachable. We keep these because we still hold their
    raintank ``deleteKey``, so they stay deletable."""
    now, out = int(time.time()), []
    for k, r in local.items():
        if k in skip:
            continue
        exp = r.get("expires_at")
        if exp is not None and exp <= now:
            continue                       # expired — raintank has dropped it too
        out.append({
            "key": k, "name": r.get("name") or "snapshot", "url": r.get("url", ""),
            "remaining": "never expires" if exp is None else f"expires in {_dur(exp - now)}",
            "deleteKey": r.get("deleteKey"), "source": "orphan",
        })
    return out


def _combined_snapshots(cfg):
    """Everything to list / act on, numbered consistently for list & delete.

    Returns ``(items, grafana_ok)``. Grafana's registry is authoritative; on top of
    it we surface any *unexpired* snapshots we recorded locally that Grafana has
    since pruned ("orphans") — still live on raintank, and still deletable because
    we kept their raintank ``deleteKey``. Each item is
    ``{key, name, url, remaining, deleteKey, source}`` with source ``"grafana"`` or
    ``"orphan"``."""
    local = {r["key"]: r for r in _load() if r.get("key")}
    try:
        gf = _grafana_snapshots(cfg)
    except _StackDown:
        return _local_only_items(local), False

    items, seen = [], set()
    for s in gf:
        seen.add(s["key"])
        rec = local.get(s["key"], {})
        items.append({
            "key": s["key"], "name": s["name"], "url": s["url"],
            "remaining": _expires_text(s["expires"]),
            "deleteKey": rec.get("deleteKey"), "source": "grafana",
        })
    items += _local_only_items(local, skip=seen)
    return items, True


def _try(call):
    """Run a delete HTTP call; treat success and already-gone (404/500) as done."""
    try:
        call()
        return True
    except urllib.error.HTTPError as e:
        return e.code in (404, 500)
    except urllib.error.URLError:
        return False


def _delete_everywhere(cfg, s):
    """Remove a snapshot as completely as possible: from Grafana's registry (when it
    still knows the key — that also asks raintank to drop it) AND from raintank
    directly via the ``deleteKey`` we stored at creation. The raintank path is what
    lets us clean up orphans Grafana has already pruned. Returns True if any path
    removed it (or it was already gone)."""
    ok = False
    if s.get("source") == "grafana":
        ok = _try(lambda: _delete(cfg["grafana"] + f"/api/snapshots/{s['key']}", headers=_auth(cfg)))
    if s.get("deleteKey"):
        ok = _try(lambda: _get(f'{cfg["raintank"]}/api/snapshots-delete/{s["deleteKey"]}')) or ok
    return ok


# --------------------------------------------------------------------------- tools
@tool(description="Publish the LeSysBot Grafana dashboard as a public snapshot on "
                  "snapshots.raintank.io and return the shareable link. `expiration` is "
                  "one of 1h, 6h, 12h, 1d, 7d, 30d, never (default 1h).")
async def share_dashboard(expiration: str = "1h") -> str:
    cfg = _cfg()
    exp = expiration.strip().lower().replace(" ", "")
    if exp not in EXPIRATIONS:
        return (f"Unknown expiration '{expiration}'. Choose one of: "
                f"{', '.join(EXPIRATIONS)}.")
    secs = EXPIRATIONS[exp]
    cfg["grafana"] = _resolve_grafana(cfg)   # find Grafana wherever it's running
    try:
        uid = cfg["uid"] or _pick_uid(cfg)
        if not uid:
            return ("No LeSysBot dashboard found in Grafana. Is the dashboard stack "
                    "running? Start it with ./scripts/start.sh (see dashboard/README.md).")
        model = _grafana(cfg, f"/api/dashboards/uid/{uid}")["dashboard"]
        title = model.get("title", "System Overview")
        _bake(cfg, model)
        name = f"{title} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        # Let Grafana publish the external snapshot: it relays the baked model to
        # raintank and returns the public URL. Posting here — rather than straight
        # to raintank — is what makes the snapshot render on Grafana 11.
        resp = _post(cfg["grafana"] + "/api/snapshots",
                     {"dashboard": model, "name": name, "expires": secs, "external": True},
                     headers=_auth(cfg))
    except _StackDown:
        where = f"Grafana at {cfg['grafana']}" if cfg["grafana_explicit"] else \
            "Grafana on the usual ports (" + ", ".join(_PORTS) + ")"
        return (f"Can't reach {where}. Start the dashboard stack first "
                f"(./scripts/start.sh), or set LESYSBOT_GRAFANA_URL if Grafana runs elsewhere.")
    except urllib.error.HTTPError as e:
        return (f"Grafana rejected the snapshot request (HTTP {e.code}: {e.reason}). "
                f"External snapshot publishing may be disabled in Grafana.")
    except urllib.error.URLError as e:
        return f"Couldn't reach Grafana to publish the snapshot: {e.reason}."

    _state_insert({
        "key": resp.get("key"), "url": resp.get("url"),
        "deleteUrl": resp.get("deleteUrl"), "deleteKey": resp.get("deleteKey"),
        "name": name, "created": datetime.now(timezone.utc).isoformat(),
        "expires_sec": secs,
        "expires_at": None if secs == 0 else int(time.time()) + secs,
    })
    # Only hand back the link once the server can actually serve it.
    ready = await _confirm_available(cfg, resp.get("key"))
    when = "never expires" if secs == 0 else f"expires in {exp}"
    tail = ("" if ready else
            "\n\nNote: it may take a few seconds to become viewable — if it says "
            "'Snapshot not found' at first, wait a moment and refresh.")
    return (f"📊 Dashboard shared — {when}:\n{resp.get('url')}\n\n"
            f"Anyone with this link can view a snapshot of your system metrics. "
            f"List your shares with /list_snapshots, remove one with /delete_snapshot.{tail}")


@tool(description="List dashboard snapshots: Grafana's /dashboard/snapshots registry plus "
                  "any still-live snapshots Grafana has pruned but we still track, each with "
                  "its public link and time left.")
async def list_snapshots() -> str:
    cfg = _cfg()
    cfg["grafana"] = _resolve_grafana(cfg)
    items, gf_ok = _combined_snapshots(cfg)
    _save(_prune(_load()))      # drop only *expired* local records (keeps live deleteKeys)
    if not items:
        return ("No dashboard snapshots in Grafana. Create one with /share_dashboard."
                if gf_ok else
                "Can't reach Grafana to list snapshots — is the dashboard stack up?")
    header = ("Dashboard snapshots (from Grafana):" if gf_ok else
              "Grafana unreachable — showing locally tracked shares (may be stale):")
    lines = [header, ""]
    for i, s in enumerate(items, 1):
        tag = ("\n   ⚠ pruned from Grafana — still live on raintank until it expires"
               if s["source"] == "orphan" else "")
        lines.append(f"{i}. {s['name']}\n   {s['url']}\n   {s['remaining']}{tag}")
    lines.append("\nRemove one with /delete_snapshot <number> (or 'all').")
    return "\n".join(lines)


@tool(description="Delete a dashboard snapshot (from Grafana and/or raintank, so orphaned "
                  "public copies are cleaned up too). `which` is its number from "
                  "/list_snapshots, its key, or 'all'.")
async def delete_snapshot(which: str) -> str:
    cfg = _cfg()
    cfg["grafana"] = _resolve_grafana(cfg)
    items, gf_ok = _combined_snapshots(cfg)
    if not items:
        return ("No dashboard snapshots to delete." if gf_ok else
                "Can't reach Grafana to delete snapshots. Start the dashboard stack first "
                "(./scripts/start.sh).")
    sel = which.strip().lower()
    if sel == "all":
        targets = list(items)
    elif sel.isdigit():
        i = int(sel) - 1
        if not 0 <= i < len(items):
            return f"No snapshot #{sel}. Use /list_snapshots to see the list."
        targets = [items[i]]
    else:
        targets = [s for s in items if s["key"] == which.strip()]
        if not targets:
            return f"No snapshot matches '{which}'. Use /list_snapshots to see the list."

    done = [s for s in targets if _delete_everywhere(cfg, s)]
    failed = [s for s in targets if s not in done]
    done_keys = {s["key"] for s in done}
    _save([r for r in _load() if r.get("key") not in done_keys])
    msg = "Snapshot deleted." if len(done) == 1 else f"Deleted {len(done)} snapshots."
    if failed:
        msg += " Couldn't delete: " + ", ".join(s["name"] for s in failed)
    if done:
        msg += " It could take an hour to be cleared from CDN caches."
    return msg


async def _confirm_available(cfg, key, attempts=6) -> bool:
    """Poll the snapshot server until the new snapshot is actually retrievable.

    raintank is usually instantly consistent, but occasionally a just-published
    snapshot 404s for a second or two — opening the link in that window shows
    'Snapshot not found'. Confirming here means we only hand back a link that
    already works. Returns False if it never confirms (then we warn instead)."""
    import asyncio

    if not key:
        return True
    for i in range(attempts):
        try:
            with urllib.request.urlopen(cfg["raintank"] + f"/api/snapshots/{key}", timeout=6) as r:
                if r.status == 200:
                    return True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return True   # some other status — it exists, just not 200
        except urllib.error.URLError:
            pass
        await asyncio.sleep(min(0.5 * (i + 1), 2.0))
    return False


def _pick_uid(cfg):
    rows = _grafana(cfg, "/api/search?tag=lesysbot&type=dash-db")
    return rows[0]["uid"] if rows else ""


def _state_insert(rec):
    recs = _load()
    recs.insert(0, rec)
    _save(recs)
