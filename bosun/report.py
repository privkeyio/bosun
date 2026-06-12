"""Plain-text/markdown maintenance digest for a spec.

The web UI is for browsing; this is for the maintainer who lives in a terminal:
one command that prints what to act on — dead candidates, a ready-to-promote
shortlist, contested PRs — from the same data the app uses. Reads cached PR
status (run `python -m bosun.github --file <spec>` first to populate it).
"""

from __future__ import annotations

from dataclasses import asdict

from . import source, suggest
from .github import _read_cache, pr_url, resolve_pr
from .spec import parse_spec


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
    return d


def _name(e: dict) -> str:
    n = e.get("name")
    if n and n != "-":
        return n
    return e.get("pr_title") or e.get("prnum") or ""


def _line(e: dict) -> str:
    pr = f"[{e['prnum']}]({e['url']})" if e.get("url") else (e.get("prnum") or "-")
    name, title = _name(e), e.get("pr_title")
    desc = name if (not title or name == title) else f"{name} — {title}"
    bits = []
    if e.get("review_level") is not None:
        bits.append(f"L{e['review_level']}")
    if e.get("acks"):
        bits.append(f"{e['acks']} ACK")
    if e.get("nacks"):
        bits.append(f"{e['nacks']} NACK")
    meta = f"  _({', '.join(bits)})_" if bits else ""
    return f"- {pr} {desc}{meta}"


def render(repo: str, ref: str, file: str, entries: list[dict], cats: dict) -> str:
    merges = [e for e in entries if e.get("kind") == "merge"]
    active = [e for e in merges if e.get("active")]
    cand = [e for e in merges if not e.get("active")]
    out = [
        f"# Knots spec digest — {file}",
        f"_source: {repo}@{ref}_",
        "",
        f"- **{len(merges)}** merge entries: {len(active)} active, {len(cand)} candidates",
        f"- candidate PR status known: **{cats['known']}/{cats['total']}**"
        + ("" if cats["known"] >= cats["total"]
           else "  (run `python -m bosun.github --file <spec>` for full coverage)"),
        "",
    ]

    def section(title, items, note):
        out.append(f"## {title} ({len(items)})")
        if note:
            out.append(f"_{note}_")
        out.append("")
        out.extend(_line(e) for e in items)
        if not items:
            out.append("_none_")
        out.append("")

    ready = sorted(cats["ready"], key=lambda e: (-(e.get("review_level") or 0), -(e.get("acks") or 0)))
    section("Ready to promote", ready, "open, reviewed, no NACK — consider including")
    section("Contested (NACKed)", cats["contested"], "has NACKs — needs a decision")
    section("Closed upstream — safe to drop", cats["closed_upstream"],
            "closed without merging upstream; "
            "`python -m bosun.github` then the web ★ suggestions emits a removal diff")
    section("Merged upstream — review", cats["merged_upstream"],
            "now merged in Core; re-PR to Knots if wanted, otherwise drop")
    if cats["stale"]:
        section("Stale (>1y, open)", cats["stale"], "no upstream activity in over a year")
    return "\n".join(out)


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Print a markdown maintenance digest for a spec.")
    ap.add_argument("--repo", default=source.DEFAULT_REPO)
    ap.add_argument("--ref", default=source.DEFAULT_REF)
    ap.add_argument("--file", required=True, help="spec file path within the repo")
    ap.add_argument("-o", "--out", help="write to this file instead of stdout")
    args = ap.parse_args()

    entries = [_enrich(e) for e in parse_spec(source.fetch_spec(args.repo, args.ref, args.file))]
    md = render(args.repo, args.ref, args.file, entries, suggest.categorize(entries))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        print(f"wrote {args.out}")
    else:
        print(md)


if __name__ == "__main__":
    _main()
