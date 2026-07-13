"""Build a static snapshot of bosun for GitHub Pages.

Pages can't run the Flask app, so instead of serving `/api/*` live we bake the
same data into JSON files and reuse the exact same frontend (CSS + render/filter/
legend/insights/suggestions JS from `web.py`), swapping only the data source.

Output (into --out, default `public/`):
  index.html                 the app, wired to the baked files (server controls hidden)
  data/index.json            list of published specs + snapshot timestamp
  data/<slug>.json           parsed + PR-enriched entries for a spec
  data/<slug>.suggest.json   categorized suggestions
  data/<slug>.cleanup.diff   the closed-upstream cleanup patch
  CNAME                       custom domain (bosun.privkey.io)

Run `--ingest` first (in CI, with a token) to refresh PR status into the cache;
without it, whatever is cached is used.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from . import source, suggest
from .github import RateLimited, _read_cache, pr_status, pr_url, resolve_pr
from .spec import parse_spec
from .web import _PAGE, KNOTS_REPO, knots_rows

# Specs published on the site. Add entries to publish more.
SPECS = [
    {"slug": "knots-next-29", "repo": "luke-jr/tmp", "ref": "knots-spec",
     "file": "knots-next-29.spec", "title": "Knots next (29.x)"},
]

CNAME = "bosun.privkey.io"

_SUG_FIELDS = ("prnum", "name", "pr_title", "url", "lineno", "pr_state",
               "review_level", "acks", "nacks", "updated_at", "status")


def _enrich(e) -> dict:
    d = asdict(e)
    d["url"] = pr_url(e.prnum)
    r = resolve_pr(e.prnum)
    s = _read_cache(*r) if r else None
    d["pr_state"] = s.get("state") if s else None
    d["review_level"] = s.get("review_level") if s else None
    d["acks"] = s.get("acks") if s else None
    d["nacks"] = s.get("nacks") if s else None
    d["pr_title"] = s.get("title") if s else None
    d["updated_at"] = s.get("updated_at") if s else None
    return d


def _ingest(entries) -> None:
    seen = set()
    for e in entries:
        r = resolve_pr(e.prnum)
        if r and r not in seen:
            seen.add(r)
            try:
                pr_status(*r)
            except RateLimited:
                print("rate limit hit; keeping cached status for the remaining PRs")
                return
            except Exception:
                pass


def _build_knots(data, ingest: bool) -> dict:
    """Bake the "open Knots PRs" pseudo-spec (data/__knots__.*) and return its
    index entry. Same JSON shape as a spec so the frontend needs no new loader."""
    rows = knots_rows(KNOTS_REPO)
    if ingest:
        for r in rows:
            try:
                pr_status(KNOTS_REPO, r["lineno"])
            except RateLimited:
                print("rate limit hit while ingesting Knots PRs; keeping cached status")
                break
            except Exception:
                pass
        rows = knots_rows(KNOTS_REPO)  # re-read with the cache now warm
    cats = suggest.categorize(rows)
    slim = {k: [{f: e.get(f) for f in _SUG_FIELDS} for e in v]
            for k, v in cats.items() if isinstance(v, list)}
    (data / "__knots__.json").write_text(json.dumps({"file": "__knots__", "entries": rows}))
    (data / "__knots__.suggest.json").write_text(
        json.dumps({"known": cats["known"], "total": cats["total"], **slim}))
    (data / "__knots__.cleanup.diff").write_text("# not applicable to the PR list\n")
    return {"slug": "__knots__", "title": "★ open Knots PRs", "repo": KNOTS_REPO,
            "ref": "-", "file": "__knots__", "merges": len(rows), "known": cats["known"]}


_STATIC_CSS = """
  #url, #go, details.src, #auto, #fetchgh, #refresh { display: none !important; }
  .genat { opacity: .6; font-size: .78rem; margin-left: .5rem; }
"""

# Replaces the server bootstrap at the tail of web.py's page. Overrides the two
# data-loaders (entries + suggestions) to read the baked files; all other JS
# (render, filters, legend, insights, sugEntry, ...) is reused unchanged.
_STATIC_TAIL = r"""loadEntries = async function () {
  const slug = $("#spec").value; if (!slug) return;
  VIEW = slug === "__knots__" ? "prs" : "spec";
  $("#status").textContent = "loading…";
  try {
    const j = await (await fetch("data/" + slug + ".json")).json();
    setData(j.entries); $("#status").textContent = "";
  } catch (e) { $("#status").textContent = "error: " + e.message; }
};
$("#suggest").onclick = async function () {
  const slug = $("#spec").value;
  $("#sugmodal").style.display = "flex"; $("#sugbody").innerHTML = "loading…";
  try {
    const j = await (await fetch("data/" + slug + ".suggest.json")).json();
    let html = `<div class="cover">Based on <b>${j.known}</b> of ${j.total} candidates with fetched status.</div>`;
    const closed = j.closed_upstream.length;
    if (closed) html += `<div class="cleanup"><div><b>Spec cleanup</b>`
      + `<div class="desc">${closed} candidate lines for PRs closed without merging upstream.</div></div>`
      + `<a class="dlbtn" href="data/${slug}.cleanup.diff" download="${slug}.cleanup.diff">download .diff</a></div>`;
    for (const [key, title, icon, cls, desc] of SUG_GROUPS) {
      const rows = j[key] || [];
      const op = "";  // all sections collapsed by default
      html += `<details class="scard ${cls}"${op}><summary class="scard-h"><span class="sicon">${icon}</span>`
        + `<h3>${title}</h3><span class="sbadge">${rows.length}</span></summary><div class="desc">${desc}</div>`
        + (rows.length ? rows.map(sugEntry).join("") : `<div class="muted">none</div>`) + `</details>`;
    }
    $("#sugbody").innerHTML = html;
  } catch (e) { $("#sugbody").textContent = "error: " + e.message; }
};
(async function () {
  let idx;
  try { idx = await (await fetch("data/index.json")).json(); }
  catch (e) { $("#status").textContent = "no data"; return; }
  $("#spec").innerHTML = idx.specs.map(s => `<option value="${s.slug}">${s.title || s.slug}</option>`).join("");
  // cloneNode drops the stale addEventListener bound to the old loadEntries.
  const clone = $("#spec").cloneNode(true);
  $("#spec").parentNode.replaceChild(clone, $("#spec"));
  $("#spec").addEventListener("change", loadEntries);
  if (idx.generated) $("#totals").insertAdjacentHTML("afterend", `<span class="genat">snapshot ${idx.generated} UTC</span>`);
  const st = restoreState();
  if (st && st.spec && idx.specs.some(s => s.slug === st.spec)) $("#spec").value = st.spec;
  pendingSect = (st && st.sect) || null;
  await loadEntries();
})();"""

_TAIL_MARKER = ("const _saved = restoreState();\n"
                "pendingSect = (_saved && _saved.sect) || null;\n"
                "loadSpecs(_saved && _saved.spec);")


def _static_html() -> str:
    page = _PAGE
    assert _TAIL_MARKER in page, "web.py bootstrap changed; update static_build tail marker"
    page = page.replace("</style>", _STATIC_CSS + "</style>")
    page = page.replace(_TAIL_MARKER, _STATIC_TAIL)
    # Hidden inputs still carry the template placeholders; fill with defaults.
    page = page.replace("%%REPO%%", source.DEFAULT_REPO).replace("%%REF%%", source.DEFAULT_REF)
    return page


def build(outdir: str, ingest: bool = False) -> None:
    out = Path(outdir)
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)

    index = {"generated": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "specs": []}

    # Build the small, high-value PR view first so it gets a fresh rate-limit
    # budget before the large spec ingest below. A failure here (e.g. a bad API
    # token) must not take down the whole site — skip the view and keep going.
    knots_entry = None
    try:
        knots_entry = _build_knots(data, ingest)
    except Exception as e:
        print(f"WARNING: skipping open-Knots-PRs view: {e}\n"
              "  the API token is likely invalid/expired — check BOSUN_GH_TOKEN / GITHUB_TOKEN")

    for spec in SPECS:
        entries = parse_spec(source.fetch_spec(spec["repo"], spec["ref"], spec["file"]))
        if ingest:
            _ingest(entries)
        enriched = [_enrich(e) for e in entries]
        cats = suggest.categorize(enriched)
        slim = {k: [{f: e.get(f) for f in _SUG_FIELDS} for e in v]
                for k, v in cats.items() if isinstance(v, list)}

        (data / f"{spec['slug']}.json").write_text(json.dumps({"file": spec["file"], "entries": enriched}))
        (data / f"{spec['slug']}.suggest.json").write_text(
            json.dumps({"known": cats["known"], "total": cats["total"], **slim}))
        # Cleanup diff = closed-upstream only (the safe set, matching the app default).
        linenos = {e["lineno"] for e in cats["closed_upstream"]}
        text = source.fetch_spec(spec["repo"], spec["ref"], spec["file"])
        (data / f"{spec['slug']}.cleanup.diff").write_text(
            suggest.cleanup_diff(text, linenos, spec["file"]) or "# nothing to remove\n")

        merges = [e for e in enriched if e.get("kind") == "merge"]
        index["specs"].append({
            "slug": spec["slug"], "title": spec["title"], "repo": spec["repo"],
            "ref": spec["ref"], "file": spec["file"],
            "merges": len(merges), "known": cats["known"],
        })

    if knots_entry:
        index["specs"].insert(0, knots_entry)
    (data / "index.json").write_text(json.dumps(index))
    (out / "index.html").write_text(_static_html())
    (out / "CNAME").write_text(CNAME + "\n")
    print(f"wrote {out}/ ({len(SPECS)} spec(s), snapshot {index['generated']} UTC)")


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Build the static Pages snapshot.")
    ap.add_argument("-o", "--out", default="public")
    ap.add_argument("--ingest", action="store_true", help="refresh PR status into the cache first")
    args = ap.parse_args()
    build(args.out, ingest=args.ingest)


if __name__ == "__main__":
    _main()
