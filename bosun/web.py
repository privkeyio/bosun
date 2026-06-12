"""Minimal zero-dependency web view for a parsed Knots spec.

Serves (or writes) a single self-contained HTML page with a sortable,
filterable table of spec entries. No framework, no pip install: just stdlib.

    python3 -m bosun.web testdata/knots-next-29.spec          # serve on :8765
    python3 -m bosun.web testdata/knots-next-29.spec -o out.html   # write file
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from .spec import parse_spec

_REPO_BY_PREFIX = {"": "bitcoin/bitcoin", "k": "bitcoinknots/bitcoin", "g": "bitcoin-core/gui"}


def pr_url(prnum: str | None) -> str | None:
    if not prnum:
        return None
    m = re.match(r"^([A-Za-z]?)(\d+)$", prnum)
    if not m:
        return None
    repo = _REPO_BY_PREFIX.get(m.group(1).lower())
    return f"https://github.com/{repo}/pull/{m.group(2)}" if repo else None


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bosun — %%TITLE%%</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.4 system-ui, sans-serif; margin: 0; padding: 1rem 1.5rem; }
  h1 { font-size: 1.1rem; margin: 0 0 .25rem; }
  .sub { opacity: .7; margin-bottom: .5rem; }
  .legend { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;
            font-size: .82rem; opacity: .9; margin-bottom: .75rem; }
  .legend .pill { margin-right: .25rem; }
  .controls { display: flex; gap: .75rem; flex-wrap: wrap; align-items: center;
              position: sticky; top: 0; background: Canvas; padding: .5rem 0; }
  input, select { font: inherit; padding: .3rem .5rem; }
  input[type=search] { min-width: 18rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: .3rem .6rem; border-bottom: 1px solid #8884;
           vertical-align: top; }
  th { cursor: pointer; user-select: none; position: sticky; top: 3rem; background: Canvas; }
  th:hover { background: #8882; }
  tr:hover td { background: #8881; }
  .pill { font-size: .8em; padding: .05rem .4rem; border-radius: .6rem; white-space: nowrap; }
  .active { background: #2a8a2a33; }
  .cand   { background: #c8881133; }
  .nack   { background: #c0303033; }
  code { font-size: .85em; opacity: .8; }
  a { color: inherit; }
  .count { opacity: .6; font-weight: normal; }
</style></head><body>
<h1>bosun</h1>
<div class="sub">%%TITLE%% · <span id="totals"></span> · <span id="shown"></span></div>
<div class="legend">
  <span><span class="pill active">●</span>active (in the build)</span>
  <span><span class="pill cand">○</span>candidate (commented-out, under consideration)</span>
  <span><span class="pill nack">○</span>rejected / broken</span>
  <span>· <b>disposition</b> = maintainer's freeform triage note</span>
  <span>· <b>PR</b> links to the source fork on GitHub</span>
</div>
<div class="controls">
  <input type="search" id="q" placeholder="search name / PR / status…">
  <select id="sect"><option value="">all sections</option>%%SECTIONS%%</select>
  <select id="state">
    <option value="">active + candidates</option>
    <option value="active">active only</option>
    <option value="cand">candidates only</option>
  </select>
  <label><input type="checkbox" id="merges" checked> merges only</label>
</div>
<table><thead><tr>
  <th data-k="active">●</th><th data-k="section">section</th>
  <th data-k="prnum">PR</th><th data-k="name">name</th>
  <th data-k="status">disposition</th><th data-k="commit">commit</th>
  <th data-k="upstream">upstream</th>
</tr></thead><tbody id="rows"></tbody></table>
<script>
const DATA = %%DATA%%;
const $ = s => document.querySelector(s);
let sortKey = "section", sortDir = 1;

function prLink(d) {
  if (!d.url) return d.prnum || "";
  return `<a href="${d.url}" target="_blank">${d.prnum}</a>`;
}
function render() {
  const q = $("#q").value.toLowerCase();
  const sect = $("#sect").value, state = $("#state").value;
  const mergesOnly = $("#merges").checked;
  let rows = DATA.filter(d => {
    if (mergesOnly && d.kind !== "merge") return false;
    if (sect && d.section !== sect) return false;
    if (state === "active" && !d.active) return false;
    if (state === "cand" && d.active) return false;
    if (q) {
      const hay = `${d.prnum||""} ${d.name||""} ${d.status||""} ${d.upstream||""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  rows.sort((a, b) => {
    const x = (a[sortKey] ?? "") + "", y = (b[sortKey] ?? "") + "";
    return x.localeCompare(y, undefined, {numeric: true}) * sortDir;
  });
  $("#shown").textContent = `${rows.length} shown`;
  $("#rows").innerHTML = rows.map(d => {
    const cls = !d.active ? (/(^|: )n?ack|broken|bad idea|not worth/i.test(d.status||"") ? "nack" : "cand") : "active";
    const dot = d.active ? "●" : "○";
    return `<tr>
      <td><span class="pill ${cls}">${dot}</span></td>
      <td>${d.section||""}</td>
      <td>${prLink(d)}</td>
      <td>${d.name||""}</td>
      <td>${d.status||""}</td>
      <td><code>${d.commit||""}</code></td>
      <td>${d.upstream ? `<code>${d.last||""}</code> ${d.upstream}` : ""}</td>
    </tr>`;
  }).join("");
}
document.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {
  const k = th.dataset.k;
  sortDir = (sortKey === k) ? -sortDir : 1; sortKey = k; render();
});
["q","sect","state","merges"].forEach(id => {
  const el = $("#"+id); el.addEventListener(el.type === "checkbox" ? "change" : "input", render);
});
const _m = DATA.filter(d => d.kind === "merge");
$("#totals").textContent = `${_m.filter(d => d.active).length} active, ${_m.filter(d => !d.active).length} candidates`;
render();
</script></body></html>"""


def build_html(entries, title: str) -> str:
    data = []
    for e in entries:
        d = asdict(e)
        d["url"] = pr_url(e.prnum)
        data.append(d)
    sections = sorted({e.section for e in entries if e.section})
    opts = "".join(f"<option>{s}</option>" for s in sections)
    return (_PAGE
            .replace("%%TITLE%%", title)
            .replace("%%SECTIONS%%", opts)
            .replace("%%DATA%%", json.dumps(data)))


def _main() -> None:
    import argparse
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    ap = argparse.ArgumentParser(description="Browse a Knots spec in the browser.")
    ap.add_argument("spec")
    ap.add_argument("-o", "--out", help="write static HTML to this file instead of serving")
    ap.add_argument("-p", "--port", type=int, default=8765)
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as fh:
        entries = parse_spec(fh.read())
    html = build_html(entries, os.path.basename(args.spec))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {args.out} ({len(html)} bytes)")
        return

    body = html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"bosun serving {args.spec} at http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    _main()
