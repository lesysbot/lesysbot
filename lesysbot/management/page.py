"""The control panel single page, inlined so it always ships with the package
(no package-data wiring needed).

The brand mark and favicon are rendered to SVG here from the sprite in
``lesysbot.core._logo`` — the same grid ``core/banner.py`` renders to the
terminal — so the web copy can't drift from the generated art. The page follows
the docs-site palette (slate + ``brand-*`` cyan) and carries a 2-state
light/dark toggle keyed on a ``data-theme`` attribute on ``<html>``.
"""
from __future__ import annotations

import base64

from lesysbot.core._logo import MARK, MARK_32, PALETTE

TRANSPARENT = "."


def _to_svg(grid: tuple[str, ...], palette: dict[str, str], scale: int = 1) -> str:
    """Pixel-exact SVG from a sprite grid — horizontal runs merge into one rect.

    Mirrors ``scripts/gen_logo.py:to_svg`` (which lives outside the package, so
    it can't be imported), the way ``banner.render`` mirrors its ANSI emitter.
    """
    h, w = len(grid), len(grid[0])
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w * scale}" height="{h * scale}" shape-rendering="crispEdges" '
        f'role="img" aria-label="LeSysBot">'
    ]
    for y, row in enumerate(grid):
        x = 0
        while x < w:
            ch = row[x]
            run = 1
            while x + run < w and row[x + run] == ch:
                run += 1
            if ch != TRANSPARENT:
                out.append(
                    f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{palette[ch]}"/>'
                )
            x += run
    out.append("</svg>")
    return "".join(out)


# The bevelled 32px mark, inlined into the header; the flat 16px cut as a
# base64 data-URI favicon. The tile is dark ink, so one mark serves both themes.
_MARK_SVG = _to_svg(MARK_32, PALETTE)
_FAVICON_HREF = "data:image/svg+xml;base64," + base64.b64encode(
    _to_svg(MARK, PALETTE).encode()
).decode()


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LeSysBot — Management</title>
<link rel="icon" type="image/svg+xml" href="<!--FAVICON-->">
<script>
  // Applied before paint so a dark-mode reload never flashes white.
  (function(){try{var t=localStorage.getItem('lesysbot-ui-theme');
    if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
</script>
<style>
  :root{
    --font-sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif;
    --font-mono:ui-monospace,"SFMono-Regular","SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
    --radius-card:.875rem;
    /* light — docs-site slate + brand ramp (src/styles/main.css) */
    --bg:#ffffff; --panel:#ffffff; --ink:#334155; --heading:#0f172a;
    --muted:#64748b; --faint:#94a3b8; --line:#e2e8f0; --chip:#f1f5f9;
    --accent:#0891b2; --link:#0e7490; --ring:#06b6d4;
    --ok:#059669; --warn:#d97706; --bad:#e11d48;
    --primary-bg:#0f172a; --primary-fg:#ffffff; --shadow:rgba(15,23,42,.10);
  }
  :root[data-theme="dark"]{
    --bg:#020617; --panel:#0f172a; --ink:#cbd5e1; --heading:#ffffff;
    --muted:#94a3b8; --faint:#64748b; --line:#1e293b; --chip:#1e293b;
    --accent:#22d3ee; --link:#67e8f9; --ring:#22d3ee;
    --ok:#34d399; --warn:#fbbf24; --bad:#fb7185;
    --primary-bg:#ffffff; --primary-fg:#0f172a; --shadow:rgba(0,0,0,.45);
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --bg:#020617; --panel:#0f172a; --ink:#cbd5e1; --heading:#ffffff;
      --muted:#94a3b8; --faint:#64748b; --line:#1e293b; --chip:#1e293b;
      --accent:#22d3ee; --link:#67e8f9; --ring:#22d3ee;
      --ok:#34d399; --warn:#fbbf24; --bad:#fb7185;
      --primary-bg:#ffffff; --primary-fg:#0f172a; --shadow:rgba(0,0,0,.45);
    }
  }
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 var(--font-sans);background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}
  :focus-visible{outline:2px solid var(--ring);outline-offset:2px;border-radius:6px}
  h1,h2,h3{color:var(--heading);letter-spacing:-.01em}
  header{display:flex;align-items:center;gap:10px;padding:11px 20px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--panel) 85%,transparent);backdrop-filter:blur(8px);position:sticky;top:0;z-index:5}
  header .mark{display:flex;flex:none}
  header .mark svg{width:30px;height:30px;display:block}
  .brand{display:flex;align-items:baseline;gap:8px;line-height:1}
  .brand-name{font-size:15px;font-weight:650;color:var(--heading);letter-spacing:-.01em}
  .brand-sub{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.14em;color:var(--faint)}
  .badge{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 10px}
  .grow{flex:1}
  .icon-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;flex:none;border:none;border-radius:.6rem;background:none;color:var(--muted);cursor:pointer;transition:background .15s,color .15s}
  .icon-btn:hover{background:var(--chip);color:var(--heading)}
  .icon-btn svg{width:18px;height:18px}
  nav{display:flex;gap:4px;padding:10px 20px 0;background:var(--panel);border-bottom:1px solid var(--line)}
  nav button{background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);padding:8px 12px;font:inherit;cursor:pointer;border-radius:6px 6px 0 0}
  nav button:hover{color:var(--heading)}
  nav button.active{color:var(--heading);border-bottom-color:var(--accent);font-weight:600}
  main{max-width:1000px;margin:0 auto;padding:22px 20px 60px}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-card);padding:14px 16px}
  .card .k{font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;font-weight:600}
  .card .v{font-size:20px;font-weight:650;margin-top:4px;color:var(--heading)}
  .card .s{font-size:12px;color:var(--muted);margin-top:2px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .dot.ok{background:var(--ok)} .dot.bad{background:var(--bad)} .dot.warn{background:var(--warn)} .dot.off{background:var(--faint)}
  /* Doctor / job output */
  .joblog{margin:0;padding:10px 12px;background:var(--panel);border:1px solid var(--line);
    border-radius:var(--radius-card);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
    font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word;
    max-height:260px;overflow:auto;margin-bottom:14px}
  .fix{margin-top:3px;font-size:12px;color:var(--brand-600)}
  .secname{margin:22px 0 8px;font-size:14px;font-weight:650}
  .secname:first-child{margin-top:0}
  label.muted{display:inline-flex;align-items:center;gap:6px;font-size:12px;cursor:pointer}
  table{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius-card);overflow:hidden}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;background:var(--chip);font-weight:600}
  tr:last-child td{border-bottom:none}
  .chip{display:inline-block;font-size:11px;font-weight:500;background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin:1px 3px 1px 0}
  .name{font-weight:600;color:var(--heading)}
  .desc{color:var(--muted);font-size:13px;max-width:420px}
  button.btn{font:inherit;font-weight:500;cursor:pointer;border-radius:.6rem;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:6px 12px;transition:border-color .15s,background .15s,color .15s}
  button.btn:hover{border-color:var(--accent);color:var(--heading)}
  button.btn.primary{background:var(--primary-bg);color:var(--primary-fg);border-color:var(--primary-bg)}
  button.btn.primary:hover{opacity:.9;color:var(--primary-fg)}
  button.btn.danger:hover{border-color:var(--bad);color:var(--bad)}
  button.btn.small{padding:4px 9px;font-size:12px}
  input,textarea{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:.6rem;padding:8px 10px}
  input{min-width:260px}
  input:focus,textarea:focus{outline:none;border-color:var(--accent)}
  textarea{width:100%;min-height:460px;font-family:var(--font-mono);font-size:13px;line-height:1.5;white-space:pre;overflow:auto}
  .muted{color:var(--muted)} .mono{font-family:var(--font-mono)}
  a{color:var(--link);text-decoration:none} a:hover{text-decoration:underline}
  .switch{cursor:pointer;border-radius:999px;border:1px solid var(--line);padding:4px 10px;font-size:12px;font-weight:500;background:var(--panel);color:var(--muted)}
  .switch.on{background:color-mix(in srgb,var(--ok) 15%,transparent);border-color:var(--ok);color:var(--ok)}
  .switch.off{background:color-mix(in srgb,var(--muted) 10%,transparent);color:var(--muted)}
  #toast{position:fixed;right:18px;bottom:18px;display:flex;flex-direction:column;gap:8px;z-index:20}
  .toast{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:.6rem;padding:10px 14px;box-shadow:0 6px 24px var(--shadow);max-width:380px}
  .toast.bad{border-left-color:var(--bad)} .toast.ok{border-left-color:var(--ok)}
  .hide{display:none}
  .note{background:var(--chip);border:1px solid var(--line);border-radius:.6rem;padding:8px 12px;font-size:13px;margin:10px 0;color:var(--muted)}
  .err{color:var(--bad);white-space:pre-wrap;font-family:var(--font-mono);font-size:12px;margin-top:8px}
  /* Messaging form */
  .seg{display:inline-flex;border:1px solid var(--line);border-radius:.7rem;padding:3px;gap:3px;background:var(--chip)}
  .seg button{font:inherit;font-weight:500;border:none;background:none;color:var(--muted);padding:6px 14px;border-radius:.5rem;cursor:pointer}
  .seg button.on{background:var(--panel);color:var(--heading);box-shadow:0 1px 3px var(--shadow)}
  .form{display:grid;gap:14px;margin-top:14px}
  .form .card h3{margin:0 0 2px;font-size:15px}
  .field{display:grid;gap:5px;margin-top:12px}
  .field>label{font-size:12px;font-weight:600;color:var(--heading)}
  .field .help{font-size:12px;color:var(--muted)}
  .field input{min-width:0;width:100%}
  .inline{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .inline input{flex:1;min-width:200px}
  .tokstate{font-size:12px;color:var(--muted)}
  .tokstate b{color:var(--heading);font-weight:600}
  .banner{display:flex;gap:10px;align-items:center;flex-wrap:wrap;border:1px solid var(--warn);background:color-mix(in srgb,var(--warn) 10%,transparent);border-radius:.6rem;padding:9px 12px;font-size:13px;margin-top:12px}
  .check{display:inline-flex;gap:8px;align-items:center;cursor:pointer;font-size:13px}
  .check input{min-width:0;width:auto;flex:none;margin:0}
  .testres{font-size:12px}
  .testres.ok{color:var(--ok)} .testres.bad{color:var(--bad)}
</style>
</head>
<body>
<header>
  <span class="mark"><!--MARK--></span>
  <span class="brand"><span class="brand-name">LeSysBot</span><span class="brand-sub">Manage</span></span>
  <span class="badge" id="ver">v…</span>
  <span class="grow"></span>
  <button class="icon-btn" id="themeToggle" type="button" aria-label="Toggle dark mode" onclick="toggleTheme()"></button>
  <span class="badge">🔒 localhost only</span>
</header>
<nav>
  <button data-tab="status" class="active">Status</button>
  <button data-tab="messaging">Messaging</button>
  <button data-tab="tools">Tools</button>
  <button data-tab="doctor">Doctor</button>
  <button data-tab="config">Config</button>
</nav>
<main>
  <section id="status">
    <div class="row" style="margin-bottom:12px"><button class="btn small" onclick="loadStatus()">↻ Refresh</button></div>
    <div class="cards" id="statusCards"></div>
    <table id="statusMeta"></table>
  </section>

  <section id="messaging" class="hide">
    <div class="row">
      <span class="muted">Where you chat with LeSysBot. Tokens are never shown here — paste a new one to replace it.</span>
      <span class="grow"></span>
      <button class="btn small" onclick="loadMessaging()">↻ Reload</button>
    </div>
    <div id="msgBanner"></div>
    <div class="form">
      <div class="card">
        <div class="k">Chat platform</div>
        <div class="seg" id="provSeg" role="radiogroup" style="margin-top:8px">
          <button type="button" data-prov="cli" role="radio">Terminal only</button>
          <button type="button" data-prov="telegram" role="radio">Telegram</button>
          <button type="button" data-prov="discord" role="radio">Discord</button>
        </div>
        <div class="s" id="provHelp" style="margin-top:8px"></div>
      </div>

      <div class="card" id="card-telegram">
        <h3>Telegram</h3>
        <div class="s">Create a bot by messaging <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → <span class="mono">/newbot</span>, then paste the token it gives you.</div>
        <div class="field">
          <label for="tok-telegram">Bot token</label>
          <div class="tokstate" id="tokstate-telegram"></div>
          <div class="inline">
            <input id="tok-telegram" type="password" autocomplete="new-password" spellcheck="false" placeholder="123456789:AA…">
            <button class="btn small" type="button" onclick="peek('telegram')" id="peek-telegram">Show</button>
            <button class="btn small" type="button" onclick="testToken('telegram')">Test</button>
            <button class="btn small danger" type="button" onclick="clearToken('telegram')">Clear</button>
          </div>
          <div class="testres" id="test-telegram"></div>
        </div>
        <div class="field">
          <label for="ids-telegram">Allowed user IDs</label>
          <input id="ids-telegram" spellcheck="false" placeholder="e.g. 123456789, 987654321">
          <div class="help">Only these Telegram users can use the bot. Message <a href="https://t.me/userinfobot" target="_blank" rel="noopener">@userinfobot</a> to get your ID. Empty = <b>anyone</b> who finds the bot.</div>
        </div>
      </div>

      <div class="card" id="card-discord">
        <h3>Discord</h3>
        <div class="s">In the <a href="https://discord.com/developers/applications" target="_blank" rel="noopener">Developer Portal</a>: New Application → Bot → Reset Token. Turn on <b>Message Content Intent</b>, and invite the bot with the <span class="mono">bot</span> and <span class="mono">applications.commands</span> scopes.</div>
        <div class="field">
          <label for="tok-discord">Bot token</label>
          <div class="tokstate" id="tokstate-discord"></div>
          <div class="inline">
            <input id="tok-discord" type="password" autocomplete="new-password" spellcheck="false" placeholder="MTA…">
            <button class="btn small" type="button" onclick="peek('discord')" id="peek-discord">Show</button>
            <button class="btn small" type="button" onclick="testToken('discord')">Test</button>
            <button class="btn small danger" type="button" onclick="clearToken('discord')">Clear</button>
          </div>
          <div class="testres" id="test-discord"></div>
        </div>
        <div class="field">
          <label for="ids-discord">Allowed user IDs</label>
          <input id="ids-discord" spellcheck="false" placeholder="e.g. 123456789012345678">
          <div class="help">Turn on Developer Mode in Discord, then right-click your name → Copy User ID. Empty = <b>anyone</b> who shares a server with the bot.</div>
        </div>
      </div>

      <div class="card" id="card-notice">
        <h3>Startup message</h3>
        <div class="s">A short system report (temperatures, disk, internet speed) sent when the service starts — e.g. right after the machine boots.</div>
        <div class="field"><label class="check"><input type="checkbox" id="sn-enabled"> Send a message when LeSysBot starts</label></div>
        <div class="field">
          <label for="sn-notify">Send it to</label>
          <input id="sn-notify" spellcheck="false" placeholder="Empty = the allowed user IDs above">
          <div class="help">Telegram chat IDs, or Discord user/channel IDs.</div>
        </div>
        <div class="field inline">
          <label class="check"><input type="checkbox" id="sn-speed"> Include an internet speed test</label>
          <input id="sn-mb" type="number" min="0.1" step="0.5" style="max-width:90px;flex:none"><span class="muted">MB download</span>
        </div>
      </div>
    </div>
    <div class="row" style="margin-top:16px">
      <button class="btn primary" onclick="saveMessaging()">Save</button>
      <button class="btn" id="restartBtn" onclick="restartService()">Restart service</button>
      <span class="muted mono" id="msgPath" style="font-size:12px"></span>
    </div>
    <div class="err" id="msgErr"></div>
  </section>

  <section id="tools" class="hide">
    <div class="row" style="margin-bottom:14px">
      <input id="installSrc" placeholder="Add a tool: paste a GitHub link, or a folder path on this machine">
      <button class="btn primary" onclick="install()">Install</button>
      <span class="grow"></span>
      <button class="btn small" onclick="update()">↻ Update all</button>
      <button class="btn small" onclick="loadTools()">↻ Refresh</button>
    </div>
    <div class="note">A tool is a folder. Copying one into the tools directory works too — a running bot picks it up within a second.</div>
    <div id="jobBox" class="hide"></div>
    <table id="toolsTable"><tbody></tbody></table>
  </section>

  <section id="doctor" class="hide">
    <div class="row" style="margin-bottom:14px">
      <span class="muted">What this machine can do, and what would unlock the rest.</span>
      <span class="grow"></span>
      <button class="btn small" onclick="loadDoctor()">↻ Re-check</button>
    </div>
    <div id="doctorBody"></div>
  </section>

  <section id="config" class="hide">
    <div class="row" style="margin-bottom:8px">
      <span class="muted mono" id="cfgPath"></span><span class="grow"></span>
      <button class="btn small" onclick="loadConfig()">↻ Reload</button>
      <button class="btn primary" onclick="saveConfig()">Save</button>
    </div>
    <div class="note">Edits are validated against the schema before saving. Restart the bot to apply — <b>tool enable/disable applies live</b>.
      Tokens and keys show as <span class="mono">&lt;hidden&gt;</span>: leave that to keep the saved value, or replace it with a new one. Telegram and Discord are easier in the <a href="#" onclick="showTab('messaging');return false">Messaging</a> tab.</div>
    <textarea id="cfgText" spellcheck="false"></textarea>
    <div class="err" id="cfgErr"></div>
  </section>
</main>
<div id="toast"></div>

<script>
const $ = (s)=>document.querySelector(s);
async function api(method, path, body){
  const r = await fetch(path, {method, headers:{'Content-Type':'application/json'},
    body: body?JSON.stringify(body):undefined});
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || (r.status+' '+r.statusText));
  return j;
}
function toast(msg, kind){ const el=document.createElement('div'); el.className='toast '+(kind||'');
  el.textContent=msg; $('#toast').appendChild(el); setTimeout(()=>el.remove(), 4200); }
function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// THEME — 2-state toggle: follows the OS until clicked, then sticks.
const SUN='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="10" r="3.6"/><path d="M10 1.6v2M10 16.4v2M3.5 3.5l1.4 1.4M15.1 15.1l1.4 1.4M1.6 10h2M16.4 10h2M3.5 16.5l1.4-1.4M15.1 4.9l1.4-1.4"/></svg>';
const MOON='<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M17 12.3A7.5 7.5 0 0 1 7.7 3a7.5 7.5 0 1 0 9.3 9.3Z"/></svg>';
function currentTheme(){
  const a=document.documentElement.getAttribute('data-theme');
  if(a==='dark'||a==='light') return a;
  return matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
}
function applyThemeIcon(){ $('#themeToggle').innerHTML = currentTheme()==='dark'?SUN:MOON; }
function toggleTheme(){
  const next = currentTheme()==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme', next);
  try{ localStorage.setItem('lesysbot-ui-theme', next); }catch(e){}
  applyThemeIcon();
}
// Track the OS setting only while the user hasn't chosen one.
matchMedia('(prefers-color-scheme:dark)').addEventListener('change', ()=>{
  if(!document.documentElement.getAttribute('data-theme')) applyThemeIcon();
});
applyThemeIcon();

// tabs
function showTab(tab){
  document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active', x.dataset.tab===tab));
  const TABS=['status','messaging','tools','doctor','config'];
  for(const t of TABS) $('#'+t).classList.toggle('hide', t!==tab);
  ({status:loadStatus, messaging:loadMessaging, tools:loadTools,
    doctor:loadDoctor, config:loadConfig}[tab])();
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));

// STATUS
async function loadStatus(){
  let st; try{ st=await api('GET','/api/status'); }catch(e){ toast('Status failed: '+e.message,'bad'); return; }
  $('#ver').textContent='v'+(st.version||'?');
  const h=st.health||{}; const hd = h.ok?'ok':'bad';
  const hsub = h.ok ? ((h.latency_ms!=null?h.latency_ms+' ms':'')+(h.model_available===false?' · model missing':'')) : (h.error||'unreachable');
  const dm=st.daemon;
  const gf=st.grafana;
  const cards=[
    ['LLM backend', `<span class="dot ${hd}"></span>${h.ok?'Reachable':'Down'}`, esc(hsub)],
    ['Provider', esc(st.provider), 'model: '+esc(st.model)],
    ['Tools', st.tools.enabled+' / '+st.tools.total+' on', st.tools.unavailable? st.tools.unavailable+' unavailable here':'all available'],
    ['Service', dm? `<span class="dot ${dm.running?'ok':'off'}"></span>${dm.running?'running':'stopped'}` : '<span class="dot off"></span>unknown',
       dm&&dm.pid? 'PID '+dm.pid+' · serves this panel' : 'serves this panel' ],
    ['Grafana',
       (gf&&gf.reachable)? `<a href="${esc(gf.dashboard_url||gf.url)}" target="_blank" rel="noopener">Open dashboard ↗</a>`
         : '<span class="dot off"></span>not running',
       (gf&&gf.reachable)? esc(gf.dashboard_url||gf.url)+(gf.version?(' · v'+gf.version):'')
         : (gf? 'not answering at '+esc(gf.url) : 'start it with: lesysbot dashboard start')],
  ];
  $('#statusCards').innerHTML=cards.map(c=>`<div class="card"><div class="k">${c[0]}</div><div class="v">${c[1]}</div><div class="s">${c[2]||''}</div></div>`).join('');
  const meta=[['Base URL',st.base_url],['Config file',st.config_path||'(built-in defaults)'],
    ['Home',st.home],['Tools dir',st.tools_dir],['Control panel port',st.panel_port]];
  $('#statusMeta').innerHTML='<tr><th>Key</th><th>Value</th></tr>'+meta.map(m=>`<tr><td>${m[0]}</td><td class="mono">${esc(m[1])}</td></tr>`).join('');
  if(st.registry_error) toast('Tool registry warning: '+st.registry_error,'bad');
}

// TOOLS
async function loadTools(){
  let d; try{ d=await api('GET','/api/tools'); }catch(e){ toast('Tools failed: '+e.message,'bad'); return; }
  const rows=d.tools||[];
  $('#toolsTable').innerHTML='<tr><th>Tool</th><th>State</th><th>Where</th><th></th></tr>'+
    (rows.length?rows.map(t=>{
      const req=(t.requires||[]).map(p=>`<span class="chip">needs ${esc(p)}</span>`).join('');
      const conf=t.confirm?'<span class="chip">confirm</span>':'';
      const avail=t.available?'':`<div class="err">⚠ ${esc(t.unavailable_reason||'unavailable here')}</div>`;
      return `<tr>
        <td><div class="name">${esc(t.name)}</div><div class="desc">${esc(t.description)}</div>${avail}</td>
        <td><span class="switch ${t.enabled?'on':'off'}" onclick="toggle('${esc(t.name)}',${!t.enabled})">${t.enabled?'enabled':'disabled'}</span></td>
        <td>${req}${conf}<div class="muted" style="font-size:11px;margin-top:3px">${t.source_kind?esc(t.source_kind):'built-in'}</div></td>
        <td><button class="btn small danger" onclick="removeTool('${esc(t.name)}')">Remove</button></td>
      </tr>`;
    }).join(''):'<tr><td colspan="4" class="muted">No tools found.</td></tr>');
}
async function toggle(name, enabled){
  try{ await api('POST','/api/tools/toggle',{name,enabled}); toast(name+(enabled?' enabled':' disabled'),'ok'); loadTools(); }
  catch(e){ toast('Toggle failed: '+e.message,'bad'); }
}
async function removeTool(name){
  if(!confirm('Remove "'+name+'"? This deletes its files.')) return;
  try{ await api('POST','/api/artifacts/remove',{name}); toast('Removed '+name,'ok'); loadTools(); }
  catch(e){ toast('Remove failed: '+e.message,'bad'); }
}

// Installs run as a background job: a zipball download plus pip can take tens of
// seconds, and a request held open that long is indistinguishable from a hang.
async function install(){
  const src=$('#installSrc').value.trim(); if(!src){toast('Enter a GitHub link or a folder path','bad');return;}
  let r; try{ r=await api('POST','/api/artifacts/install',{source:src}); }
  catch(e){ toast('Install failed: '+e.message,'bad'); return; }
  $('#installSrc').value='';
  await followJob(r.job, 'Installed');
  loadTools();
}
async function update(){
  let r; try{ r=await api('POST','/api/artifacts/update',{}); }
  catch(e){ toast('Update failed: '+e.message,'bad'); return; }
  await followJob(r.job, 'Updated');
  loadTools();
}
async function followJob(id, verb){
  const box=$('#jobBox'); box.classList.remove('hide');
  for(;;){
    let j; try{ j=await api('GET','/api/jobs/'+id); }
    catch(e){ toast('Lost track of the job: '+e.message,'bad'); return; }
    box.innerHTML='<pre class="joblog">'+esc((j.lines||[]).join('\n'))+'</pre>';
    box.scrollTop=box.scrollHeight;
    if(j.state==='done'){ toast(verb+' ✓ ('+j.elapsed+'s)','ok'); return; }
    if(j.state==='failed'){ toast('Failed: '+j.error,'bad'); return; }
    await new Promise(r=>setTimeout(r,600));
  }
}

// DOCTOR
async function loadDoctor(){
  let d; try{ d=await api('GET','/api/prereq'); }catch(e){ toast('Doctor failed: '+e.message,'bad'); return; }
  $('#doctorBody').innerHTML=(d.reports||[]).map(rep=>{
    const rows=rep.results.map(r=>{
      const state=r.satisfied?'<span class="dot ok"></span>ok'
        : r.optional?'<span class="dot off"></span><span class="muted">not available</span>'
        : '<span class="dot bad"></span>missing';
      const fix=(!r.satisfied&&r.fix)?`<div class="fix">→ ${esc(r.fix)}</div>`:'';
      return `<tr><td class="mono">${esc(r.type)} ${esc(r.value)}</td><td>${state}</td>
              <td><span class="muted">${esc(r.detail)}</span>${fix}</td></tr>`;
    }).join('');
    return `<h3 class="secname">${esc(rep.name)} ${rep.ok?'':'<span class="chip">needs attention</span>'}</h3>
            <table>${rows}</table>`;
  }).join('') || '<p class="muted">Nothing to check.</p>';
}

// MESSAGING — the browser never receives a token; it sends one only when typed.
const PROV_HELP={cli:'Chat in a terminal with <span class="mono">lesysbot chat</span>. The service runs without a chat platform.',
  telegram:'The service answers you in Telegram.', discord:'The service answers you in Discord (DMs or a channel).'};
let msg=null, msgProv='cli', clearTok={};
function setProv(p){
  msgProv=p;
  document.querySelectorAll('#provSeg button').forEach(b=>{const on=b.dataset.prov===p; b.classList.toggle('on',on); b.setAttribute('aria-checked',on);});
  $('#provHelp').innerHTML=PROV_HELP[p]||'';
  $('#card-telegram').classList.toggle('hide', p!=='telegram');
  $('#card-discord').classList.toggle('hide', p!=='discord');
  $('#card-notice').classList.toggle('hide', p==='cli');
}
document.querySelectorAll('#provSeg button').forEach(b=>b.onclick=()=>setProv(b.dataset.prov));
function tokState(name){
  const t=(msg&&msg[name]&&msg[name].token)||{state:'empty'};
  if(clearTok[name]) return '<span class="dot warn"></span>Will be <b>cleared</b> on save.';
  if(t.state==='set') return '<span class="dot ok"></span><b>Saved</b>'+(t.hint?' · ends in <span class="mono">…'+esc(t.hint)+'</span>':'')+' — leave the box empty to keep it.';
  if(t.state==='env') return '<span class="dot '+(t.env_set?'ok':'bad')+'"></span>From environment variable <span class="mono">$'+esc(t.env_var)+'</span> ('+(t.env_set?'set':'<b>not set</b>')+'). Paste a token to store it in config.yaml instead.';
  return '<span class="dot bad"></span><b>Not set</b> — paste your bot token.';
}
function renderTok(name){ $('#tokstate-'+name).innerHTML=tokState(name); }
function peek(name){ const i=$('#tok-'+name); const show=i.type==='password'; i.type=show?'text':'password'; $('#peek-'+name).textContent=show?'Hide':'Show'; }
function clearToken(name){
  if(!confirm('Remove the saved '+name+' token from config.yaml when you save?')) return;
  clearTok[name]=true; $('#tok-'+name).value=''; renderTok(name);
}
async function loadMessaging(){
  let d; try{ d=await api('GET','/api/messaging'); }catch(e){ $('#msgErr').textContent=e.message; toast('Messaging failed: '+e.message,'bad'); return; }
  msg=d; clearTok={}; $('#msgErr').textContent='';
  for(const n of ['telegram','discord']){
    $('#tok-'+n).value=''; $('#tok-'+n).type='password'; $('#peek-'+n).textContent='Show'; $('#test-'+n).textContent='';
    $('#ids-'+n).value=(d[n].allowed_user_ids||[]).join(', ');
    renderTok(n);
  }
  const sn=d.startup_notice||{};
  $('#sn-enabled').checked=!!sn.enabled; $('#sn-notify').value=(sn.notify||[]).join(', ');
  $('#sn-speed').checked=!!sn.speedtest; $('#sn-mb').value=sn.speedtest_mb;
  setProv(d.provider||'cli');
  $('#msgPath').textContent=d.path+(d.exists?'':'  (will be created)');
  $('#restartBtn').classList.toggle('hide', !(d.service&&d.service.installed));
  renderMsgBanner();
}
function renderMsgBanner(){
  const d=msg; if(!d) return;
  const svc=d.service&&d.service.installed;
  $('#msgBanner').innerHTML = d.restart_needed
    ? `<div class="banner"><span>⚠ Saved settings differ from what the service is running (currently <b>${esc(d.running_provider)}</b>). `+
      (svc?'Restart to apply.</span><button class="btn small" onclick="restartService()">Restart now</button>'
          :'Restart LeSysBot to apply.</span>')+'</div>'
    : '';
}
function msgPayload(){
  const p={provider:msgProv, startup_notice:{enabled:$('#sn-enabled').checked, notify:$('#sn-notify').value,
    speedtest:$('#sn-speed').checked, speedtest_mb:parseFloat($('#sn-mb').value||'5')}};
  for(const n of ['telegram','discord']){
    const s={allowed_user_ids:$('#ids-'+n).value};
    const typed=$('#tok-'+n).value.trim();
    if(typed) s.token=typed; else if(clearTok[n]) s.token='';
    p[n]=s;
  }
  return p;
}
async function saveMessaging(){
  $('#msgErr').textContent='';
  try{ const r=await api('POST','/api/messaging',msgPayload()); toast(r.note||'Saved','ok'); await loadMessaging(); }
  catch(e){ $('#msgErr').textContent=e.message; toast('Not saved','bad'); }
}
async function testToken(name){
  const out=$('#test-'+name); out.className='testres'; out.textContent='Checking…';
  try{
    const r=await api('POST','/api/messaging/test',{provider:name, token:$('#tok-'+name).value.trim()});
    out.className='testres '+(r.ok?'ok':'bad');
    out.textContent=r.ok?('✓ Works — this is '+r.bot+(r.name?' ('+r.name+')':'')):('✗ '+r.error);
  }catch(e){ out.className='testres bad'; out.textContent='✗ '+e.message; }
}
async function restartService(){
  if(!confirm('Restart the LeSysBot service now? The bot (and this page) will be offline for a few seconds.')) return;
  let r; try{ r=await api('POST','/api/service/restart',{}); }catch(e){ toast('Restart failed: '+e.message,'bad'); return; }
  toast(r.note||'Restarting…','ok');
  // Wait for the panel to come back, then refresh what the service now runs.
  const t0=Date.now(); await new Promise(res=>setTimeout(res,1500));
  while(Date.now()-t0<30000){
    try{ await api('GET','/api/ping'); break; }catch(e){ await new Promise(res=>setTimeout(res,1000)); }
  }
  loadStatus(); if(!$('#messaging').classList.contains('hide')) loadMessaging();
}

// CONFIG
async function loadConfig(){
  try{ const d=await api('GET','/api/config'); $('#cfgText').value=d.yaml; $('#cfgPath').textContent=d.path+(d.exists?'':'  (will be created)'); $('#cfgErr').textContent=''; }
  catch(e){ toast('Config load failed: '+e.message,'bad'); }
}
async function saveConfig(){
  $('#cfgErr').textContent='';
  try{ const r=await api('POST','/api/config',{yaml:$('#cfgText').value}); toast(r.note||'Saved','ok'); }
  catch(e){ $('#cfgErr').textContent=e.message; toast('Save rejected','bad'); }
}

loadStatus();
</script>
</body>
</html>
"""

PAGE = _TEMPLATE.replace("<!--MARK-->", _MARK_SVG).replace("<!--FAVICON-->", _FAVICON_HREF)
