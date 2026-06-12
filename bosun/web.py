"""Flask web app for browsing Knots specs across repos/forks.

The core (spec/source/ack) is pure stdlib; only this UI layer needs Flask.
Loads spec files from a GitHub repo/branch (default luke-jr/tmp @ knots-spec),
with a picker to switch the spec file or point at your own fork.

    python3 -m bosun.web                         # serve, default source
    python3 -m bosun.web --repo me/tmp --ref my-specs
"""

from __future__ import annotations

from dataclasses import asdict

from flask import Flask, Response, jsonify, request

from . import source, suggest
from .github import RateLimited, _read_cache, pr_status, pr_url, resolve_pr
from .spec import parse_spec

app = Flask(__name__)
app.config["DEFAULT_REPO"] = source.DEFAULT_REPO
app.config["DEFAULT_REF"] = source.DEFAULT_REF


def _entry_dict(e) -> dict:
    d = asdict(e)
    d["url"] = pr_url(e.prnum)
    r = resolve_pr(e.prnum)
    status = _read_cache(*r) if r else None  # cache-only; no network on page load
    d["pr_state"] = status.get("state") if status else None
    d["review_level"] = status.get("review_level") if status else None
    d["acks"] = status.get("acks") if status else None
    d["nacks"] = status.get("nacks") if status else None
    d["pr_title"] = status.get("title") if status else None
    d["updated_at"] = status.get("updated_at") if status else None
    d["fetched"] = status.get("fetched") if status else None
    return d


@app.get("/")
def index() -> Response:
    html = (_PAGE
            .replace("%%REPO%%", app.config["DEFAULT_REPO"])
            .replace("%%REF%%", app.config["DEFAULT_REF"]))
    return Response(html, mimetype="text/html")


@app.get("/api/specs")
def api_specs():
    repo = request.args.get("repo", source.DEFAULT_REPO)
    ref = request.args.get("ref", source.DEFAULT_REF)
    try:
        return jsonify(repo=repo, ref=ref, specs=source.list_specs(repo, ref))
    except Exception as e:  # network / not-found / rate-limit
        return jsonify(error=str(e)), 502


@app.get("/api/entries")
def api_entries():
    repo = request.args.get("repo", source.DEFAULT_REPO)
    ref = request.args.get("ref", source.DEFAULT_REF)
    file = request.args.get("file")
    if not file:
        return jsonify(error="file parameter required"), 400
    try:
        text = source.fetch_spec(repo, ref, file)
        return jsonify(file=file, entries=[_entry_dict(e) for e in parse_spec(text)])
    except Exception as e:
        return jsonify(error=str(e)), 502


_SUG_FIELDS = ("prnum", "name", "pr_title", "url", "lineno", "pr_state",
               "review_level", "acks", "nacks", "updated_at", "status")


@app.get("/api/suggest")
def api_suggest():
    repo = request.args.get("repo", source.DEFAULT_REPO)
    ref = request.args.get("ref", source.DEFAULT_REF)
    file = request.args.get("file")
    if not file:
        return jsonify(error="file parameter required"), 400
    try:
        entries = [_entry_dict(e) for e in parse_spec(source.fetch_spec(repo, ref, file))]
    except Exception as e:
        return jsonify(error=str(e)), 502
    cats = suggest.categorize(entries)
    slim = {k: [{f: e.get(f) for f in _SUG_FIELDS} for e in v]
            for k, v in cats.items() if isinstance(v, list)}
    return jsonify(known=cats["known"], total=cats["total"], **slim)


@app.get("/api/cleanup.diff")
def api_cleanup_diff():
    repo = request.args.get("repo", source.DEFAULT_REPO)
    ref = request.args.get("ref", source.DEFAULT_REF)
    file = request.args.get("file")
    if not file:
        return Response("file parameter required\n", status=400, mimetype="text/plain")
    include = [s for s in request.args.get("include", "merged,closed").split(",") if s]
    try:
        text = source.fetch_spec(repo, ref, file)
        cats = suggest.categorize([_entry_dict(e) for e in parse_spec(text)])
    except Exception as e:
        return Response(f"error: {e}\n", status=502, mimetype="text/plain")
    linenos = {e["lineno"] for short in include
               for e in cats.get(suggest.REMOVABLE.get(short, ""), [])}
    diff = suggest.cleanup_diff(text, linenos, file) or "# nothing to remove\n"
    return Response(diff, mimetype="text/plain")


@app.get("/api/pr")
def api_pr():
    repo = request.args.get("repo")
    num = request.args.get("num", type=int)
    if not repo or not num:
        return jsonify(error="repo and num required"), 400
    try:
        return jsonify(pr_status(repo, num, refresh=request.args.get("refresh") == "1"))
    except RateLimited as e:
        return jsonify(error=str(e)), 429
    except Exception as e:
        return jsonify(error=str(e)), 502


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bosun</title>
<style>
  :root { color-scheme: light dark; --line: #8883; }
  * { box-sizing: border-box; }
  body { font: 14px/1.45 system-ui, sans-serif; margin: 0; padding: .9rem 1.2rem; }
  input, select, button { font: inherit; padding: .3rem .5rem; }
  button { cursor: pointer; }

  .topbar { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap;
            padding-bottom: .7rem; border-bottom: 1px solid var(--line); margin-bottom: .9rem; }
  .topbar h1 { font-size: 1.15rem; margin: 0; }
  #url { flex: 1; min-width: 18rem; }
  .topbar .spec select { min-width: 12rem; }
  details.src { font-size: .85rem; }
  details.src summary { cursor: pointer; opacity: .7; }
  details.src #repo { min-width: 10rem; } details.src #ref { min-width: 7rem; }
  details.src label { margin-right: .4rem; }

  .layout { display: flex; gap: 1.4rem; align-items: flex-start; }
  .panel { flex: 0 0 220px; position: sticky; top: .5rem; display: flex; flex-direction: column;
           gap: .8rem; max-height: calc(100vh - 1rem); overflow-y: auto; padding-right: .35rem; }
  .panel input[type=search], .panel select { width: 100%; }
  main { flex: 1; min-width: 0; }
  body.panel-collapsed .panel { display: none; }
  .toggle { background: none; border: 1px solid #8884; border-radius: .4rem; padding: .25rem .55rem; }
  @media (max-width: 820px) {
    .layout { flex-direction: column; } .panel { position: static; flex: auto; width: 100%; max-height: none; }
  }

  .fgroup { display: flex; flex-direction: column; gap: .4rem; }
  .fhead { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; opacity: .5; }
  .fchips { display: flex; flex-wrap: wrap; gap: .3rem; }
  .frow { font-size: .9rem; display: flex; align-items: center; gap: .35rem; }
  .panel hr { width: 100%; border: none; border-top: 1px solid var(--line); margin: .15rem 0; }
  .panel button:not(.clearf) { width: 100%; text-align: left; }
  .clearf { font-size: .78rem; opacity: .8; background: none; align-self: flex-start;
            border: 1px solid #8884; border-radius: .6rem; padding: .2rem .55rem; }

  .chip { display: inline-block; font-size: .78em; padding: .12rem .5rem; border-radius: .7rem; white-space: nowrap; }
  .fchips .chip { cursor: pointer; border: 1px solid #8884; }
  .fchips .chip:hover { border-color: currentColor; }
  .fchips .chip.on { box-shadow: inset 0 0 0 2px currentColor; font-weight: 600; }
  .chip .ct { opacity: .55; margin-left: .15rem; }
  .n-active{background:#2a8a2a55} .n-needs-review{background:#2b6cb055}
  .n-needs-concept{background:#7c3aed55} .n-needs-work{background:#c8881155}
  .n-triage{background:#88888855} .n-deferred{background:#0d948855}
  .n-wontfix{background:#c0303055} .n-other,.n-untagged{background:#8888882a}
  .st { display: inline-block; font-size: .78em; padding: .08rem .45rem; border-radius: .6rem; }
  .st-merged{background:#7c3aed55} .st-open{background:#2a8a2a55}
  .st-closed{background:#c0303055} .st-missing,.st-unknown{background:#8888882a}
  .lv { display: inline-block; font-size: .78em; padding: .08rem .4rem; border-radius: .5rem; background:#8888882a; }
  .lv2 { background:#c8881144 } .lv3 { background:#2a8a2a55 } .nackt { color:#c03030 }

  .sub { opacity: .7; margin-bottom: .4rem; font-size: .9rem; }
  #status { font-style: italic; }
  .insights { font-size: .85rem; margin: 0 0 .7rem; display: flex; flex-wrap: wrap; gap: .35rem .5rem; align-items: center; }
  .insights b { font-weight: 600; }
  .insights .ins { cursor: pointer; padding: .08rem .45rem; border-radius: .6rem; background: #8888882a; }
  .insights .ins:hover { outline: 1px solid currentColor; }
  .insights .ins.merged { background:#7c3aed44 } .insights .ins.open { background:#2a8a2a44 } .insights .ins.nack { background:#c0303044 }

  .tablewrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: .32rem .6rem; border-bottom: 1px solid #8884; vertical-align: top; }
  th { cursor: pointer; user-select: none; position: sticky; top: 0; background: Canvas; white-space: nowrap; }
  th:hover { background: #8882; } th.sorted { background: #8883; }
  tbody tr:nth-child(even) td { background: #80808012; }
  tr:hover td { background: #8081; }
  code { font-size: .85em; opacity: .8; } a { color: inherit; } .raw { opacity: .65; }
  .dot { opacity: .55; } .dot.on { color: #2a8a2a; opacity: 1; }
  .age { opacity: .65; font-size: .85em; white-space: nowrap; }
  tr.drop td { opacity: .45; } tr.drop:hover td { opacity: .72; }
  .empty { text-align: center; padding: 1.5rem; opacity: .6; }
  #suggest { background: #2b6cb033; }
  .modal { display: none; position: fixed; inset: 0; background: #0007;
           align-items: flex-start; justify-content: center; z-index: 10; padding: 3vh 1rem; }
  .modal .card { background: Canvas; border: 1px solid var(--line); border-radius: .6rem;
                 max-width: 860px; width: 100%; max-height: 90vh; overflow: auto; padding: 1rem 1.2rem; }
  .cardhead { display: flex; justify-content: space-between; align-items: center;
              position: sticky; top: 0; background: Canvas; padding-bottom: .5rem; }
  .x { background: none; border: none; font-size: 1.1rem; cursor: pointer; }
  .cover { font-size: .82rem; opacity: .7; margin-bottom: .5rem; }
  .desc { font-size: .82rem; opacity: .7; }
  .muted { opacity: .6; }
  .cleanup { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
             background: #2b6cb022; border: 1px solid #2b6cb055; border-radius: .5rem;
             padding: .6rem .8rem; margin: .4rem 0 .9rem; }
  .dlbtn { background: #2b6cb0; color: #fff; border: none; border-radius: .4rem;
           padding: .45rem .9rem; font-weight: 600; cursor: pointer; white-space: nowrap; }
  .sg-merged{--c:#7c3aed} .sg-closed{--c:#c03030} .sg-ready{--c:#2a8a2a}
  .sg-contested{--c:#c88811} .sg-stale{--c:#888}
  .scard { border-left: 4px solid var(--c); background: #80808014; border-radius: .4rem;
           padding: .55rem .8rem; margin: .7rem 0; }
  .scard-h { display: flex; align-items: center; gap: .5rem; margin-bottom: .15rem; }
  .scard-h h3 { margin: 0; font-size: 1rem; }
  .sicon { width: 1.35rem; height: 1.35rem; display: inline-flex; align-items: center;
           justify-content: center; border-radius: 50%; background: var(--c); color: #fff;
           font-size: .8rem; font-weight: 700; }
  .sbadge { margin-left: auto; background: var(--c); color: #fff; border-radius: 1rem;
            padding: .05rem .6rem; font-weight: 600; font-size: .85rem; }
  .se { display: grid; grid-template-columns: 4.5rem 1fr auto; gap: .5rem; align-items: baseline;
        padding: .22rem 0; border-bottom: 1px solid #8882; font-size: .9rem; }
  .se:last-child { border-bottom: none; }
  .se-pr { font-family: ui-monospace, monospace; }
  .se-meta { display: flex; gap: .3rem; align-items: center; white-space: nowrap; }
</style></head><body>

<header class="topbar">
  <button id="togglepanel" class="toggle" title="Show/hide filters">☰</button>
  <h1>bosun</h1>
  <input id="url" type="url" placeholder="paste a GitHub spec URL: https://github.com/<owner>/<repo>/blob/<ref>/<file>.spec">
  <button id="go">load</button>
  <label class="spec">spec <select id="spec"></select></label>
  <details class="src">
    <summary>source</summary>
    <label>repo <input id="repo" value="%%REPO%%"></label>
    <label>ref <input id="ref" value="%%REF%%"></label>
    <button id="loadspecs">list specs</button>
  </details>
  <button id="suggest" title="Actionable maintenance suggestions + a spec-cleanup diff">★ suggestions</button>
</header>

<div class="layout">
  <aside class="panel">
    <input type="search" id="q" placeholder="search…  ( / )">
    <div class="fgroup"><div class="fhead">State</div><div class="fchips" id="g-state"></div></div>
    <div class="fgroup"><div class="fhead">Disposition</div><div class="fchips" id="g-bucket"></div></div>
    <div class="fgroup" id="wrap-prstate"><div class="fhead">PR state</div><div class="fchips" id="g-prstate"></div></div>
    <div class="fgroup" id="wrap-level"><div class="fhead">Review level</div><div class="fchips" id="g-level"></div></div>
    <div class="fgroup"><div class="fhead">Section</div><select id="sect"><option value="">all sections</option></select></div>
    <label class="frow"><input type="checkbox" id="merges" checked> merges only</label>
    <button class="clearf" id="clearf">clear filters</button>
    <hr>
    <div class="fhead">GitHub status</div>
    <label class="frow"><input type="checkbox" id="auto"> auto-fetch as I filter</label>
    <button id="fetchgh" title="Fetch live PR state + ACK level for the rows shown">fetch status (shown)</button>
    <button id="refresh" title="Re-fetch shown rows, ignoring the cache">↻ refresh shown</button>
    <button id="exportcsv" title="Download the shown rows as CSV">export CSV</button>
  </aside>

  <main>
    <div class="sub"><span id="totals"></span> · <span id="shown"></span> · <span id="status"></span></div>
    <div class="insights" id="insights"></div>
    <div class="tablewrap"><table><thead><tr>
      <th data-k="active">●</th><th data-k="section">section</th>
      <th data-k="prnum">PR</th><th data-k="name">name</th>
      <th data-k="status_norm">disposition</th>
      <th data-k="pr_state">PR state</th><th data-k="review_level">review</th>
      <th data-k="updated_at">age</th>
      <th data-k="commit">commit</th><th data-k="upstream">upstream</th>
    </tr></thead><tbody id="rows"></tbody></table></div>
  </main>
</div>

<div id="sugmodal" class="modal"><div class="card">
  <div class="cardhead"><b>Spec suggestions</b><button id="sugclose" class="x">✕</button></div>
  <div id="sugbody"></div>
</div></div>

<script>
let DATA = [], sortKey = "section", sortDir = 1, pendingSect = null;
const $ = s => document.querySelector(s);
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const prLink = d => d.url
  ? `<a href="${d.url}" target="_blank"${d.pr_title ? ` title="${esc(d.pr_title)}"` : ""}>${esc(d.prnum)}</a>`
  : esc(d.prnum || "");

const sel = { buckets: new Set(), states: new Set(), prstate: new Set(), level: new Set(), nack: new Set() };
const selSet = kind => ({ state: sel.states, bucket: sel.buckets, prstate: sel.prstate, level: sel.level }[kind]);

function setData(arr) {
  DATA = arr;
  const secs = [...new Set(DATA.filter(d => d.section).map(d => d.section))].sort();
  $("#sect").innerHTML = '<option value="">all sections</option>'
    + secs.map(s => `<option>${esc(s)}</option>`).join("");
  if (pendingSect) { $("#sect").value = pendingSect; pendingSect = null; }
  buildLegend();
  render();
}

function chip(kind, val, label, count, cls) {
  return `<button class="chip ${cls||''}" data-kind="${kind}" data-val="${val}">`
    + `${label} <span class="ct">${count}</span></button>`;
}

function tally(rows, key) {
  const m = {}; rows.forEach(d => { const v = d[key]; if (v != null) m[v] = (m[v] || 0) + 1; });
  return m;
}

function fillGroup(id, items) {
  $(id).innerHTML = items.map(([kind, val, label, count, cls]) => chip(kind, val, label, count, cls)).join("");
}

function buildLegend() {
  const merges = DATA.filter(d => d.kind === "merge");
  const act = merges.filter(d => d.active).length, cand = merges.length - act;
  const bc = tally(merges, "status_norm");
  const ps = tally(merges, "pr_state");
  const lv = tally(merges.filter(d => d.pr_state), "review_level");
  $("#totals").textContent = `${merges.length} merges · ${act} active / ${cand} candidates`;

  fillGroup("#g-state", [["state", "active", "● active", act], ["state", "cand", "○ candidate", cand]]);
  fillGroup("#g-bucket", Object.keys(bc).sort((a, b) => bc[b] - bc[a]).map(b => ["bucket", b, b, bc[b], "n-" + b]));

  const psKeys = ["open", "merged", "closed", "missing"].filter(s => ps[s]);
  $("#wrap-prstate").style.display = psKeys.length ? "" : "none";
  fillGroup("#g-prstate", psKeys.map(s => ["prstate", s, s, ps[s], "st st-" + s]));

  const lvKeys = [3, 2, 1, 0].filter(l => lv[l]);
  $("#wrap-level").style.display = lvKeys.length ? "" : "none";
  fillGroup("#g-level", lvKeys.map(l => ["level", l, "L" + l, lv[l], "lv lv" + l]));

  document.querySelectorAll(".fchips .chip").forEach(el => el.onclick = () => {
    const set = selSet(el.dataset.kind), v = el.dataset.val;
    set.has(v) ? set.delete(v) : set.add(v);
    syncChips(); render();
  });
  syncChips();
  insights();
}

function syncChips() {
  document.querySelectorAll(".fchips .chip").forEach(el =>
    el.classList.toggle("on", selSet(el.dataset.kind).has(el.dataset.val)));
}

function applyFilter(spec) {
  Object.values(sel).forEach(s => s.clear());
  $("#q").value = ""; $("#sect").value = ""; $("#merges").checked = true;
  for (const k of ["states", "prstate", "level", "buckets", "nack"])
    (spec[k] || []).forEach(v => sel[k].add(String(v)));
  syncChips(); render();
}

function insights() {
  const cand = DATA.filter(d => d.kind === "merge" && !d.active);
  const known = cand.filter(d => d.pr_state);
  const n = s => known.filter(d => d.pr_state === s).length;
  const unrev = known.filter(d => !d.review_level).length;
  const nacked = known.filter(d => d.nacks > 0).length;
  const ins = (cls, label, f) => `<span class="ins ${cls}" data-f='${JSON.stringify(f)}'>${label}</span>`;
  $("#insights").innerHTML = cand.length ? [
    `candidates: <b>${cand.length}</b>`,
    `status known: ${known.length}/${cand.length}`,
    ins("merged", "merged upstream: " + n("merged"), { states: ["cand"], prstate: ["merged"] }),
    ins("open", "open: " + n("open"), { states: ["cand"], prstate: ["open"] }),
    ins("", "closed: " + n("closed"), { states: ["cand"], prstate: ["closed"] }),
    ins("", "0 reviews: " + unrev, { states: ["cand"], level: ["0"] }),
    nacked ? ins("nack", "NACKed: " + nacked, { states: ["cand"], nack: [1] }) : "",
  ].filter(Boolean).join(" · ") : "";
  $("#insights").querySelectorAll("[data-f]").forEach(el =>
    el.onclick = () => applyFilter(JSON.parse(el.dataset.f)));
}

function ago(iso) {
  if (!iso) return "";
  const days = (Date.now() - Date.parse(iso)) / 86400000;
  if (days < 1) return "today";
  if (days < 30) return Math.round(days) + "d";
  if (days < 365) return Math.round(days / 30) + "mo";
  return (days / 365).toFixed(1) + "y";
}

const LS = "bosun.view";
function saveState() {
  try {
    localStorage.setItem(LS, JSON.stringify({
      repo: $("#repo").value, ref: $("#ref").value, spec: $("#spec").value,
      q: $("#q").value, sect: $("#sect").value, merges: $("#merges").checked,
      auto: $("#auto").checked, sortKey, sortDir,
      collapsed: document.body.classList.contains("panel-collapsed"),
      buckets: [...sel.buckets], states: [...sel.states],
      prstate: [...sel.prstate], level: [...sel.level], nack: [...sel.nack],
    }));
  } catch (e) {}
}
function restoreState() {
  let st; try { st = JSON.parse(localStorage.getItem(LS)); } catch (e) {}
  if (!st) return null;
  if (st.repo) $("#repo").value = st.repo;
  if (st.ref) $("#ref").value = st.ref;
  if (st.q) $("#q").value = st.q;
  if (typeof st.merges === "boolean") $("#merges").checked = st.merges;
  if (typeof st.auto === "boolean") $("#auto").checked = st.auto;
  if (st.collapsed) document.body.classList.add("panel-collapsed");
  if (st.sortKey) { sortKey = st.sortKey; sortDir = st.sortDir || 1; }
  sel.buckets = new Set(st.buckets || []); sel.states = new Set(st.states || []);
  sel.prstate = new Set(st.prstate || []); sel.level = new Set(st.level || []);
  sel.nack = new Set(st.nack || []);
  return st;
}

function updateSortIndicators() {
  document.querySelectorAll("th[data-k]").forEach(th => {
    if (th.dataset.label === undefined) th.dataset.label = th.textContent;
    th.classList.toggle("sorted", th.dataset.k === sortKey);
    th.textContent = th.dataset.label + (th.dataset.k === sortKey ? (sortDir > 0 ? " ▲" : " ▼") : "");
  });
}

function filtered() {
  const q = $("#q").value.toLowerCase(), sect = $("#sect").value, mergesOnly = $("#merges").checked;
  let rows = DATA.filter(d => {
    if (mergesOnly && d.kind !== "merge") return false;
    if (sect && d.section !== sect) return false;
    if (sel.buckets.size && !sel.buckets.has(d.status_norm)) return false;
    if (sel.states.size && !sel.states.has(d.active ? "active" : "cand")) return false;
    if (sel.prstate.size && !sel.prstate.has(d.pr_state)) return false;
    if (sel.level.size && !sel.level.has(String(d.review_level))) return false;
    if (sel.nack.size && !(d.nacks > 0)) return false;
    if (q && !`${d.prnum||""} ${d.name||""} ${d.status||""} ${d.upstream||""} ${d.pr_title||""}`.toLowerCase().includes(q)) return false;
    return true;
  });
  rows.sort((a, b) => ((a[sortKey] ?? "") + "").localeCompare((b[sortKey] ?? "") + "",
    undefined, {numeric: true}) * sortDir);
  return rows;
}

function reviewCell(d) {
  if (d.review_level == null) return "";
  let s = `<span class="lv lv${d.review_level}">L${d.review_level}</span>`;
  if (d.acks) s += ` ${d.acks} ACK`;
  if (d.nacks) s += ` <span class="nackt">${d.nacks} NACK</span>`;
  return s;
}

function render() {
  updateSortIndicators();
  const rows = filtered();
  $("#shown").textContent = `${rows.length} shown`;
  if (!rows.length) {
    $("#rows").innerHTML = '<tr><td colspan="10" class="empty">no rows match — adjust filters or clear them</td></tr>';
    saveState(); return;
  }
  $("#rows").innerHTML = rows.map(d => `<tr class="${!d.active && d.pr_state === 'merged' ? 'drop' : ''}">
    <td>${d.active ? '<span class="dot on">●</span>' : '<span class="dot">○</span>'}</td>
    <td>${esc(d.section)}</td>
    <td>${prLink(d)}</td>
    <td${d.pr_title ? ` title="${esc(d.pr_title)}"` : ""}>${esc(d.name)}</td>
    <td><span class="chip n-${d.status_norm}">${d.status_norm}</span> <span class="raw">${esc(d.status||"")}</span></td>
    <td>${d.pr_state ? `<span class="st st-${d.pr_state}">${d.pr_state}</span>` : ""}</td>
    <td>${reviewCell(d)}</td>
    <td class="age" title="${esc(d.updated_at||"")}">${ago(d.updated_at)}</td>
    <td><code>${esc(d.commit||"")}</code></td>
    <td>${d.upstream ? `<code>${esc(d.last||"")}</code> ${esc(d.upstream)}` : ""}</td>
  </tr>`).join("");
  saveState();
  maybeAutoFetch();
}

let fetching = false;
async function fetchGh(force = false, auto = false) {
  if (fetching) return;
  const todo = filtered().filter(d => d.url && (force || d.pr_state == null));
  const cap = 80;
  const list = todo.slice(0, cap);
  if (!list.length) {
    if (!auto) $("#status").textContent = "nothing to fetch (shown rows already loaded or have no PR)";
    return;
  }
  fetching = true;
  let done = 0, stop = false;
  const q = [...list];
  const note = todo.length > cap ? ` (capped at ${cap} of ${todo.length})` : "";
  const refresh = force ? "&refresh=1" : "";
  async function worker() {
    while (q.length && !stop) {
      const d = q.shift();
      const m = d.url.match(/github\\.com\\/([^/]+\\/[^/]+)\\/pull\\/(\\d+)/);
      try {
        const r = await fetch(`/api/pr?repo=${encodeURIComponent(m[1])}&num=${m[2]}${refresh}`);
        const j = await r.json();
        if (r.status === 429) { stop = true; $("#status").textContent = "rate limited — set GITHUB_TOKEN or use gh auth. " + (j.error||""); return; }
        if (r.ok) DATA.filter(x => x.prnum === d.prnum).forEach(x => {
          x.pr_state = j.state; x.review_level = j.review_level; x.acks = j.acks;
          x.nacks = j.nacks; x.pr_title = j.title; x.updated_at = j.updated_at;
        });
      } catch (e) {}
      $("#status").textContent = `fetching ${++done}/${list.length}${note}…`;
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
  fetching = false;
  if (!stop) $("#status").textContent = `done (${done}${note})`;
  buildLegend();  // refresh PR-state / review-level facet counts + insights
  render();
}

let autoTimer;
function maybeAutoFetch() {
  if (!$("#auto").checked || fetching) return;
  clearTimeout(autoTimer);
  autoTimer = setTimeout(() => fetchGh(false, true), 500);
}

const SUG_GROUPS = [
  ["merged_upstream", "Merged upstream", "↑", "sg-merged", "Now merged into the source repo — the candidate line is likely redundant (or pull it in)."],
  ["closed_upstream", "Closed upstream", "✕", "sg-closed", "Closed without merging — usually abandoned or rejected. Safe to remove."],
  ["ready", "Ready to promote", "✓", "sg-ready", "Open, at least one solid review, no NACK. Consider including in the build."],
  ["contested", "Contested", "!", "sg-contested", "Has NACKs — needs a decision before acting."],
  ["stale", "Stale", "⏳", "sg-stale", "Open but no upstream activity in over a year. Worth revisiting."],
];

function sugEntry(e) {
  const pr = e.url ? `<a href="${e.url}" target="_blank"${e.pr_title ? ` title="${esc(e.pr_title)}"` : ""}>${esc(e.prnum)}</a>` : esc(e.prnum);
  const meta = [
    e.pr_state ? `<span class="st st-${e.pr_state}">${e.pr_state}</span>` : "",
    e.review_level != null ? `<span class="lv lv${e.review_level}">L${e.review_level}</span>` : "",
    e.nacks ? `<span class="st st-closed">${e.nacks} NACK</span>` : "",
    e.updated_at ? `<span class="age">${ago(e.updated_at)}</span>` : "",
  ].filter(Boolean).join(" ");
  return `<div class="se"><span class="se-pr">${pr}</span>`
    + `<span class="se-name">${esc(e.name)}${e.pr_title ? ` <span class="muted">— ${esc(e.pr_title)}</span>` : ""}</span>`
    + `<span class="se-meta">${meta}</span></div>`;
}

async function openSuggest() {
  const repo = $("#repo").value.trim(), ref = $("#ref").value.trim(), file = $("#spec").value;
  $("#sugmodal").style.display = "flex";
  $("#sugbody").innerHTML = "loading…";
  try {
    const r = await fetch(`/api/suggest?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}&file=${encodeURIComponent(file)}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    let html = `<div class="cover">Based on <b>${j.known}</b> of ${j.total} candidates with fetched status.`
      + (j.known < j.total ? ` Enable auto-fetch or click “fetch status” for fuller coverage.` : "") + `</div>`;
    const rm = j.merged_upstream.length + j.closed_upstream.length;
    if (rm) html += `<div class="cleanup"><div><b>Spec cleanup</b>`
      + `<div class="desc">${rm} candidate lines for PRs no longer open upstream (merged or closed).</div></div>`
      + `<button id="dldiff" class="dlbtn">download .diff</button></div>`;
    for (const [key, title, icon, cls, desc] of SUG_GROUPS) {
      const rows = j[key] || [];
      html += `<div class="scard ${cls}"><div class="scard-h">`
        + `<span class="sicon">${icon}</span><h3>${title}</h3><span class="sbadge">${rows.length}</span></div>`
        + `<div class="desc">${desc}</div>`
        + (rows.length ? rows.map(sugEntry).join("") : `<div class="muted">none</div>`) + `</div>`;
    }
    $("#sugbody").innerHTML = html;
    const dl = document.getElementById("dldiff");
    if (dl) dl.onclick = () => {
      const a = document.createElement("a");
      a.href = `/api/cleanup.diff?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}&file=${encodeURIComponent(file)}&include=merged,closed`;
      a.download = (file || "bosun").replace(/[^a-z0-9.-]/gi, "_") + ".cleanup.diff";
      a.click();
    };
  } catch (e) { $("#sugbody").textContent = "error: " + e.message; }
}

function exportCsv() {
  const cols = ["active", "section", "prnum", "name", "status_norm", "status",
                "pr_state", "review_level", "acks", "nacks", "updated_at", "commit", "upstream"];
  const cell = v => { v = v == null ? "" : String(v); return /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const rows = filtered();
  const csv = [cols.join(",")].concat(rows.map(d => cols.map(c => cell(d[c])).join(","))).join("\\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = ($("#spec").value || "bosun").replace(/[^a-z0-9.-]/gi, "_") + ".csv";
  a.click(); URL.revokeObjectURL(a.href);
}

async function loadSpecs(prefer) {
  const repo = $("#repo").value.trim(), ref = $("#ref").value.trim();
  $("#status").textContent = "loading spec list…";
  try {
    const r = await fetch(`/api/specs?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    const prev = $("#spec").value;
    $("#spec").innerHTML = j.specs.map(s => `<option>${esc(s)}</option>`).join("");
    const def = j.specs.find(s => s.includes("knots-next-29")) || j.specs.find(s => s.includes("next")) || j.specs[j.specs.length-1];
    $("#spec").value = (prefer && j.specs.includes(prefer)) ? prefer
      : (j.specs.includes(prev) ? prev : (def || ""));
    $("#status").textContent = "";
    loadEntries();
  } catch (e) { $("#status").textContent = "error: " + e.message; }
}

// Accepts github.com/<owner>/<repo>/blob/<ref>/<path> or the raw.githubusercontent.com form.
function loadUrl() {
  const u = $("#url").value.trim();
  if (!u) return;
  const m = u.match(/github\\.com\\/([^/]+\\/[^/]+)\\/blob\\/([^/]+)\\/(.+?)(?:[?#].*)?$/)
        || u.match(/raw\\.githubusercontent\\.com\\/([^/]+\\/[^/]+)\\/([^/]+)\\/(.+?)(?:[?#].*)?$/);
  if (!m) { $("#status").textContent = "couldn't parse that — expected …/blob/<ref>/<file>.spec"; return; }
  $("#repo").value = m[1];
  $("#ref").value = m[2];
  loadSpecs(decodeURIComponent(m[3]));
}

async function loadEntries() {
  const repo = $("#repo").value.trim(), ref = $("#ref").value.trim(), file = $("#spec").value;
  if (!file) return;
  $("#status").textContent = "loading " + file + "…";
  try {
    const r = await fetch(`/api/entries?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}&file=${encodeURIComponent(file)}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    setData(j.entries);
    $("#status").textContent = "";
  } catch (e) { $("#status").textContent = "error: " + e.message; }
}

document.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {
  const k = th.dataset.k; sortDir = (sortKey === k) ? -sortDir : 1; sortKey = k; render();
});
["q","sect","merges"].forEach(id => {
  const el = $("#"+id); el.addEventListener(el.type === "checkbox" ? "change" : "input", render);
});
$("#loadspecs").onclick = () => loadSpecs();
$("#go").onclick = loadUrl;
$("#url").addEventListener("keydown", e => { if (e.key === "Enter") loadUrl(); });
$("#url").addEventListener("paste", () => setTimeout(loadUrl, 0));
$("#fetchgh").onclick = () => fetchGh(false);
$("#refresh").onclick = () => fetchGh(true);
$("#exportcsv").onclick = exportCsv;
$("#suggest").onclick = openSuggest;
$("#togglepanel").onclick = () => { document.body.classList.toggle("panel-collapsed"); saveState(); };
$("#sugclose").onclick = () => $("#sugmodal").style.display = "none";
$("#sugmodal").onclick = e => { if (e.target.id === "sugmodal") $("#sugmodal").style.display = "none"; };
$("#clearf").onclick = () => {
  Object.values(sel).forEach(s => s.clear());
  $("#q").value = ""; $("#sect").value = "";
  syncChips(); render();
};
$("#auto").addEventListener("change", () => { saveState(); maybeAutoFetch(); });
$("#spec").addEventListener("change", loadEntries);
document.addEventListener("keydown", e => {
  if (e.key === "/" && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
    e.preventDefault(); $("#q").focus();
  }
});

const _saved = restoreState();
pendingSect = (_saved && _saved.sect) || null;
loadSpecs(_saved && _saved.spec);
</script></body></html>"""


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Browse Knots specs across forks.")
    ap.add_argument("--repo", default=source.DEFAULT_REPO, help="default GitHub owner/repo")
    ap.add_argument("--ref", default=source.DEFAULT_REF, help="default branch/ref")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    app.config["DEFAULT_REPO"] = args.repo
    app.config["DEFAULT_REF"] = args.ref
    print(f"bosun: http://{args.host}:{args.port}  (source: {args.repo}@{args.ref})")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    _main()
