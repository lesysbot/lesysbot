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
  <button data-tab="tools">Tools</button>
  <button data-tab="config">Config</button>
</nav>
<main>
  <section id="status">
    <div class="row" style="margin-bottom:12px"><button class="btn small" onclick="loadStatus()">↻ Refresh</button></div>
    <div class="cards" id="statusCards"></div>
    <table id="statusMeta"></table>
  </section>

  <section id="tools" class="hide">
    <div class="row" style="margin-bottom:14px">
      <input id="installSrc" placeholder="owner/repo[/subdir][@ref]  or a github.com URL">
      <button class="btn primary" onclick="install()">Install tool</button>
      <span class="grow"></span>
      <button class="btn small" onclick="loadTools()">↻ Refresh</button>
    </div>
    <table id="toolsTable"><tbody></tbody></table>
  </section>

  <section id="config" class="hide">
    <div class="row" style="margin-bottom:8px">
      <span class="muted mono" id="cfgPath"></span><span class="grow"></span>
      <button class="btn small" onclick="loadConfig()">↻ Reload</button>
      <button class="btn primary" onclick="saveConfig()">Save</button>
    </div>
    <div class="note">Edits are validated against the schema before saving. Restart the bot to apply — <b>tool enable/disable applies live</b>.</div>
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
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  for(const t of ['status','tools','config']) $('#'+t).classList.toggle('hide', t!==b.dataset.tab);
  if(b.dataset.tab==='tools') loadTools();
  if(b.dataset.tab==='config') loadConfig();
  if(b.dataset.tab==='status') loadStatus();
});

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
       (gf&&gf.reachable)? `<a href="${esc(gf.url)}" target="_blank" rel="noopener">Open dashboard ↗</a>`
         : '<span class="dot off"></span>not running',
       (gf&&gf.reachable)? esc(gf.url)+(gf.version?(' · v'+gf.version):'')
         : (gf? 'not answering at '+esc(gf.url) : 'start monitoring/scripts/start.sh')],
  ];
  $('#statusCards').innerHTML=cards.map(c=>`<div class="card"><div class="k">${c[0]}</div><div class="v">${c[1]}</div><div class="s">${c[2]||''}</div></div>`).join('');
  const meta=[['Base URL',st.base_url],['Config file',st.config_path||'(built-in defaults)'],
    ['Home',st.home],['Tools dir',st.tools_dir],['Control panel port',st.webui_port]];
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
async function install(){
  const src=$('#installSrc').value.trim(); if(!src){toast('Enter a GitHub source','bad');return;}
  toast('Installing '+src+' …');
  try{ const r=await api('POST','/api/tools/install',{source:src}); toast('Installed: '+(r.installed||[]).join(', '),'ok'); $('#installSrc').value=''; loadTools(); }
  catch(e){ toast('Install failed: '+e.message,'bad'); }
}
async function removeTool(name){
  if(!confirm('Remove tool package for "'+name+'"? This deletes its files.')) return;
  try{ await api('POST','/api/tools/remove',{name}); toast('Removed '+name,'ok'); loadTools(); }
  catch(e){ toast('Remove failed: '+e.message,'bad'); }
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
