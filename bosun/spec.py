"""Parser for Bitcoin Knots assembly spec files (knots-spec).

A spec file is the recipe the assemble-knots.pl driver replays to build a
release: an ordered list of merge directives plus commented-out candidates
tagged with a disposition (``Needs review``, ``Triage``, ``Broken`` ...).

This module turns that file into structured ``SpecEntry`` records so review
and triage state can be tracked and compared across forks instead of living
only as freeform comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

PRNUM = r"[A-Za-z]?\d+|-|n/a"
HASH = r"[0-9a-f]{7,}"

_ENTRY = re.compile(
    rf"""^
    (?:(?P<flags>[am]+)\s+)?                       # rare merge flags (a/m)
    (?P<prnum>{PRNUM})\s+
    (?P<name>\S+)                                  # branch / feature name
    (?:\s+\(C:(?P<cpatch>[0-9a-f]+)\))?            # manual conflict patch
    (?:\s+(?P<commit>{HASH}))?                     # bare lastapply pin
    (?:\s+last=(?P<last>{HASH})(?:\s+(?P<upstream>!?\S+))?)?
    \s*$""",
    re.VERBOSE,
)
_CHECK_LAST = re.compile(
    rf"^\(CHECK-LAST\)\s+last=(?P<last>{HASH})\s+(?P<upstream>!?\S+)\s*$"
)
_DIRECTIVE = re.compile(r"^n/a\s+\((?P<func>[^)]+)\)")
_PRNUM_HEAD = re.compile(rf"({PRNUM})(\s|$)")


@dataclass
class SpecEntry:
    lineno: int
    section: str | None
    active: bool                # in the build, vs a commented-out candidate
    kind: str                   # merge | check-last | directive | meta | comment
    status: str | None          # disposition tag(s): "Needs review", "Triage: Partial"
    prnum: str | None
    name: str | None
    commit: str | None          # bare lastapply pin
    last: str | None            # last= upstream pin
    upstream: str | None        # upstream branch
    conflict_patch: str | None
    comment: str | None         # inline trailing note, or full text for pure comments
    raw: str


def _strip_inline_comment(body: str) -> tuple[str, str | None]:
    m = re.search(r"\s#\s?(.*)$", body)
    if m:
        return body[: m.start()].rstrip(), m.group(1).strip() or None
    return body.rstrip(), None


def _split_status(text: str) -> tuple[str | None, str, bool]:
    """Peel leading ``Word:`` / ``Word?`` disposition segments off a comment.

    Returns (status, remainder, looks_like_entry). Segments are only treated as
    status if what remains eventually starts with a PR-number token, so notes
    like ``https://...`` or ``Related: #32447`` are left as plain comments.
    """
    parts: list[str] = []
    rest = text.strip()
    while not _PRNUM_HEAD.match(rest):
        m = re.match(r"[^:?]*[:?]", rest)
        if not m:
            break
        parts.append(m.group(0).rstrip(" :?"))
        rest = rest[m.end() :].strip()
    is_entry = bool(_PRNUM_HEAD.match(rest))
    status = ": ".join(p for p in parts if p) if (is_entry and parts) else None
    return status, rest, is_entry


def _parse_body(body: str) -> dict:
    """Classify and parse an entry body (active or candidate)."""
    body, inline = _strip_inline_comment(body)

    m = _CHECK_LAST.match(body)
    if m:
        return dict(kind="check-last", last=m["last"], upstream=m["upstream"],
                    comment=inline)

    m = _DIRECTIVE.match(body)
    if m:
        return dict(kind="directive", name=m["func"], comment=inline)

    m = _ENTRY.match(body)
    if m:
        return dict(kind="merge", prnum=m["prnum"], name=m["name"],
                    commit=m["commit"], last=m["last"], upstream=m["upstream"],
                    conflict_patch=m["cpatch"], comment=inline)

    return dict(kind="comment", comment=body)


def parse_spec(text: str) -> list[SpecEntry]:
    entries: list[SpecEntry] = []
    section: str | None = None

    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("@"):
            section = stripped[1:]
            continue

        # Top-level meta directives (no leading indent in practice).
        if re.match(r"^#?(timestamp|checkout|lastapply)\b", stripped):
            entries.append(SpecEntry(i, section, not stripped.startswith("#"),
                                     "meta", None, None, stripped.split()[0].lstrip("#"),
                                     None, None, None, None, None, line))
            continue

        commented = stripped.startswith("#")
        if commented:
            status, rest, is_entry = _split_status(stripped.lstrip("#").strip())
            if not is_entry:
                entries.append(SpecEntry(i, section, False, "comment", None, None,
                                         None, None, None, None, None, stripped.lstrip("#").strip(), line))
                continue
            parsed = _parse_body(rest)
            active = False
        else:
            status = None
            parsed = _parse_body(stripped)
            active = True

        entries.append(SpecEntry(
            lineno=i, section=section, active=active, kind=parsed["kind"],
            status=status, prnum=parsed.get("prnum"), name=parsed.get("name"),
            commit=parsed.get("commit"), last=parsed.get("last"),
            upstream=parsed.get("upstream"), conflict_patch=parsed.get("conflict_patch"),
            comment=parsed.get("comment"), raw=line,
        ))
    return entries


def _main() -> None:
    import argparse
    import collections
    import json
    import sys

    ap = argparse.ArgumentParser(description="Parse a Knots assembly spec file.")
    ap.add_argument("spec", help="path to a .spec file")
    ap.add_argument("--json", action="store_true", help="dump entries as JSON")
    ap.add_argument("--summary", action="store_true", help="print a summary")
    ap.add_argument("--status", help="only entries whose status contains this (case-insensitive)")
    ap.add_argument("--section", help="only entries in this section")
    ap.add_argument("--candidates", action="store_true", help="only commented-out candidates")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as fh:
        entries = parse_spec(fh.read())

    if args.section:
        entries = [e for e in entries if e.section == args.section]
    if args.status:
        entries = [e for e in entries if e.status and args.status.lower() in e.status.lower()]
    if args.candidates:
        entries = [e for e in entries if not e.active and e.kind == "merge"]

    if args.json:
        json.dump([asdict(e) for e in entries], sys.stdout, indent=2)
        print()
        return

    if args.summary:
        merges = [e for e in entries if e.kind == "merge"]
        active = [e for e in merges if e.active]
        cand = [e for e in merges if not e.active]
        print(f"entries: {len(entries)}  merges: {len(merges)}  "
              f"(active: {len(active)}, candidates: {len(cand)})")
        print("\nby section (active merges):")
        by_sec = collections.Counter(e.section for e in active)
        for sec, n in by_sec.most_common():
            print(f"  {n:4}  {sec}")
        print("\ncandidate disposition (commented-out merges):")
        by_status = collections.Counter((e.status or "(untagged)") for e in cand)
        for st, n in by_status.most_common():
            print(f"  {n:4}  {st}")
        return

    for e in entries:
        if e.kind != "merge":
            continue
        mark = "  " if e.active else "??"
        tag = f"[{e.status}] " if e.status else ""
        print(f"{mark} {e.prnum or '-':>6}  {tag}{e.name or ''}")


if __name__ == "__main__":
    _main()
