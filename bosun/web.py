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

from . import source
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


@app.get("/api/pr")
def api_pr():
    repo = request.args.get("repo")
    num = request.args.get("num", type=int)
    if not repo or not num:
        return jsonify(error="repo and num required"), 400
    try:
        return jsonify(pr_status(repo, num))
    except RateLimited as e:
        return jsonify(error=str(e)), 429
    except Exception as e:
        return jsonify(error=str(e)), 502


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bosun</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.4 system-ui, sans-serif; margin: 0; padding: 1rem 1.5rem; }
  h1 { font-size: 1.1rem; margin: 0 0 .25rem; }
  .sub { opacity: .7; margin-bottom: .5rem; }
  .source, .controls { display: flex; gap: .6rem; flex-wrap: wrap; align-items: center; }
  .source { margin-bottom: .5rem; }
  .controls { position: sticky; top: 0; background: Canvas; padding: .5rem 0; z-index: 2; }
  input, select, button { font: inherit; padding: .3rem .5rem; }
  input[type=search] { min-width: 16rem; }
  #repo { min-width: 12rem; } #ref { min-width: 8rem; }
  .legend { display: flex; gap: .8rem; align-items: center; flex-wrap: wrap;
            font-size: .8rem; opacity: .9; margin: .25rem 0 .75rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: .3rem .6rem; border-bottom: 1px solid #8884; vertical-align: top; }
  th { cursor: pointer; user-select: none; position: sticky; top: 3rem; background: Canvas; }
  th:hover { background: #8882; } tr:hover td { background: #8881; }
  code { font-size: .85em; opacity: .8; } a { color: inherit; } .raw { opacity: .7; }
  .dot { opacity: .55; } .dot.on { color: #2a8a2a; opacity: 1; }
  .chip { font-size: .78em; padding: .05rem .45rem; border-radius: .7rem; white-space: nowrap; }
  .n-active{background:#2a8a2a55} .n-needs-review{background:#2b6cb055}
  .n-needs-concept{background:#7c3aed55} .n-needs-work{background:#c8881155}
  .n-triage{background:#88888855} .n-deferred{background:#0d948855}
  .n-wontfix{background:#c0303055} .n-other,.n-untagged{background:#8888882a}
  .st { font-size: .78em; padding: .05rem .4rem; border-radius: .6rem; }
  .st-merged{background:#7c3aed55} .st-open{background:#2a8a2a55}
  .st-closed{background:#c0303055} .st-missing,.st-unknown{background:#8888882a}
  .lv { font-size: .78em; padding: .05rem .35rem; border-radius: .5rem; background:#8888882a; }
  .lv2 { background:#c8881144 } .lv3 { background:#2a8a2a55 } .nackt { color:#c03030 }
  #status { opacity: .7; font-style: italic; }
</style></head><body>
<h1>bosun</h1>
<div class="sub"><span id="totals"></span> · <span id="shown"></span> · <span id="status"></span></div>

<div class="source">
  <label>repo <input id="repo" value="%%REPO%%"></label>
  <label>ref <input id="ref" value="%%REF%%"></label>
  <button id="loadspecs">load</button>
  <label>spec <select id="spec"></select></label>
</div>

<div class="legend">
  <span><span class="dot on">●</span>active (in the build)</span>
  <span><span class="dot">○</span>candidate</span>
  <span>· buckets:</span>
  <span class="chip n-needs-review">needs-review</span>
  <span class="chip n-needs-concept">needs-concept</span>
  <span class="chip n-needs-work">needs-work</span>
  <span class="chip n-triage">triage</span>
  <span class="chip n-deferred">deferred</span>
  <span class="chip n-wontfix">wontfix</span>
</div>

<div class="controls">
  <input type="search" id="q" placeholder="search name / PR / status…">
  <select id="sect"><option value="">all sections</option></select>
  <select id="norm"><option value="">all buckets</option></select>
  <select id="state">
    <option value="">active + candidates</option>
    <option value="active">active only</option>
    <option value="cand">candidates only</option>
  </select>
  <label><input type="checkbox" id="merges" checked> merges only</label>
  <button id="fetchgh" title="Fetch live PR state + ACK level for the rows shown (cached after)">fetch GitHub status (shown)</button>
</div>

<table><thead><tr>
  <th data-k="active">●</th><th data-k="section">section</th>
  <th data-k="prnum">PR</th><th data-k="name">name</th>
  <th data-k="status_norm">disposition</th>
  <th data-k="pr_state">PR state</th><th data-k="review_level">review</th>
  <th data-k="commit">commit</th><th data-k="upstream">upstream</th>
</tr></thead><tbody id="rows"></tbody></table>

<script>
let DATA = [], sortKey = "section", sortDir = 1;
const $ = s => document.querySelector(s);
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const prLink = d => d.url ? `<a href="${d.url}" target="_blank">${esc(d.prnum)}</a>` : esc(d.prnum || "");

function setData(arr) {
  DATA = arr;
  const secs = [...new Set(DATA.filter(d => d.section).map(d => d.section))].sort();
  $("#sect").innerHTML = '<option value="">all sections</option>'
    + secs.map(s => `<option>${esc(s)}</option>`).join("");
  const merges = DATA.filter(d => d.kind === "merge");
  const counts = {};
  merges.forEach(d => counts[d.status_norm] = (counts[d.status_norm] || 0) + 1);
  $("#norm").innerHTML = '<option value="">all buckets</option>'
    + Object.keys(counts).sort().map(k => `<option value="${k}">${k} (${counts[k]})</option>`).join("");
  $("#totals").textContent = `${merges.filter(d => d.active).length} active, `
    + `${merges.filter(d => !d.active).length} candidates`;
  render();
}

function filtered() {
  const q = $("#q").value.toLowerCase(), sect = $("#sect").value,
        norm = $("#norm").value, state = $("#state").value, mergesOnly = $("#merges").checked;
  let rows = DATA.filter(d => {
    if (mergesOnly && d.kind !== "merge") return false;
    if (sect && d.section !== sect) return false;
    if (norm && d.status_norm !== norm) return false;
    if (state === "active" && !d.active) return false;
    if (state === "cand" && d.active) return false;
    if (q && !`${d.prnum||""} ${d.name||""} ${d.status||""} ${d.upstream||""}`.toLowerCase().includes(q)) return false;
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
  const rows = filtered();
  $("#shown").textContent = `${rows.length} shown`;
  $("#rows").innerHTML = rows.map(d => `<tr>
    <td>${d.active ? '<span class="dot on">●</span>' : '<span class="dot">○</span>'}</td>
    <td>${esc(d.section)}</td>
    <td>${prLink(d)}</td>
    <td>${esc(d.name)}</td>
    <td><span class="chip n-${d.status_norm}">${d.status_norm}</span> <span class="raw">${esc(d.status||"")}</span></td>
    <td>${d.pr_state ? `<span class="st st-${d.pr_state}">${d.pr_state}</span>` : ""}</td>
    <td>${reviewCell(d)}</td>
    <td><code>${esc(d.commit||"")}</code></td>
    <td>${d.upstream ? `<code>${esc(d.last||"")}</code> ${esc(d.upstream)}` : ""}</td>
  </tr>`).join("");
}

async function fetchGh() {
  const todo = filtered().filter(d => d.url && d.pr_state == null);
  const cap = 80;
  const list = todo.slice(0, cap);
  if (!list.length) { $("#status").textContent = "nothing to fetch (shown rows already loaded or have no PR)"; return; }
  let done = 0, stop = false;
  const q = [...list];
  const note = todo.length > cap ? ` (capped at ${cap} of ${todo.length})` : "";
  async function worker() {
    while (q.length && !stop) {
      const d = q.shift();
      const m = d.url.match(/github\\.com\\/([^/]+\\/[^/]+)\\/pull\\/(\\d+)/);
      try {
        const r = await fetch(`/api/pr?repo=${encodeURIComponent(m[1])}&num=${m[2]}`);
        const j = await r.json();
        if (r.status === 429) { stop = true; $("#status").textContent = "rate limited — set GITHUB_TOKEN or use gh auth. " + (j.error||""); return; }
        if (r.ok) DATA.filter(x => x.prnum === d.prnum).forEach(x => {
          x.pr_state = j.state; x.review_level = j.review_level; x.acks = j.acks; x.nacks = j.nacks;
        });
      } catch (e) {}
      $("#status").textContent = `fetching ${++done}/${list.length}${note}…`;
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
  if (!stop) $("#status").textContent = `done (${done}${note})`;
  render();
}

async function loadSpecs() {
  const repo = $("#repo").value.trim(), ref = $("#ref").value.trim();
  $("#status").textContent = "loading spec list…";
  try {
    const r = await fetch(`/api/specs?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    const prev = $("#spec").value;
    $("#spec").innerHTML = j.specs.map(s => `<option>${esc(s)}</option>`).join("");
    const def = j.specs.find(s => s.includes("knots-next-29")) || j.specs.find(s => s.includes("next")) || j.specs[j.specs.length-1];
    $("#spec").value = j.specs.includes(prev) ? prev : (def || "");
    $("#status").textContent = "";
    loadEntries();
  } catch (e) { $("#status").textContent = "error: " + e.message; }
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
["q","sect","norm","state","merges"].forEach(id => {
  const el = $("#"+id); el.addEventListener(el.type === "checkbox" ? "change" : "input", render);
});
$("#loadspecs").onclick = loadSpecs;
$("#fetchgh").onclick = fetchGh;
$("#spec").addEventListener("change", loadEntries);
loadSpecs();
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
