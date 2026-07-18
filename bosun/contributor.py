"""Contributor-side preflight for the Knots assembly model.

Knots is not merged, it is assembled: each release replays a spec that checks out
a base and merges a curated set of branches on top (see CONTRIBUTING.md in the
knots-assembly repo). A change only lands if its branch is something the
assembler can replay. This checks that BEFORE you ask a maintainer to add it,
catching the two things the assembler hard-rejects:

  poison    an upstream branch (master, the dev line, ...) merged INTO your
            branch. The assembler dies "Branch <x> is poisoned". Fix: rebase
            onto the base, do not merge upstream in.

  conflict  your branch does not merge cleanly onto the base, so someone would
            have to hand-maintain a resolution diff. Fix: rebase onto the base
            and resolve there.

Read-only: the merge test runs in a throwaway worktree (via bosun.daggy), so your
repo's working tree is never touched.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from bosun.daggy import _git, _is_ancestor, _is_repo, merge_clean


def _rev_parse(repo, ref) -> str | None:
    r = _git(repo, "rev-parse", "--verify", "--quiet", ref, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def _poison_commit(repo, base, upstream) -> str | None:
    """The earliest commit `upstream` has beyond `base` (first-parent). A branch
    that contains it has had `upstream` merged in, exactly what the assembler
    rejects. Returns the SHA, or None if `upstream` is not ahead of `base`."""
    r = _git(repo, "log", f"{base}..{upstream}", "--first-parent",
             "--reverse", "--format=%H", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().split("\n", 1)[0].strip()


@dataclass
class Preflight:
    base: str
    branch: str
    upstream: str
    poison: str | None = None          # the offending upstream commit, if poisoned
    merges: bool = True                # merges cleanly onto base
    conflicts: list[str] = field(default_factory=list)
    upstream_absent: bool = False      # upstream ref not found, poison unchecked

    @property
    def poisoned(self) -> bool:
        return self.poison is not None

    @property
    def clean(self) -> bool:
        return self.merges

    @property
    def ready(self) -> bool:
        return not self.poisoned and self.clean and not self.upstream_absent

    def report(self) -> str:
        lines = []
        if self.poisoned:
            lines.append(f"  ✗ upstream merged in: {self.upstream} commit "
                         f"{self.poison[:10]} is reachable from your branch")
            lines.append(f"      rebase onto {self.base} instead of merging upstream in; "
                         f"the assembler dies 'Branch <x> is poisoned'")
        elif self.upstream_absent:
            lines.append(f"  ! could not check for upstream merges: ref "
                         f"'{self.upstream}' not found")
            lines.append("      pass --upstream <ref> (e.g. origin/master or the "
                         "dev branch you started from)")
        else:
            lines.append("  ✓ no upstream merged in")
        if self.clean:
            lines.append(f"  ✓ merges cleanly onto {self.base}")
        else:
            where = ", ".join(self.conflicts) or "(merge failed)"
            lines.append(f"  ✗ conflicts with {self.base}: {where}")
            lines.append(f"      rebase onto {self.base} and resolve, so no "
                         "hand-kept resolution diff is needed")
        lines.append("READY: the assembler can replay this branch" if self.ready
                     else "NOT READY: fix the above before asking a maintainer to add it")
        return "\n".join(lines)


def preflight(repo, branch, base, upstream="master") -> Preflight:
    pf = Preflight(base=base, branch=branch, upstream=upstream)
    if _rev_parse(repo, upstream) is None:
        pf.upstream_absent = True
    else:
        poison = _poison_commit(repo, base, upstream)
        if poison is not None and _is_ancestor(repo, poison, branch):
            pf.poison = poison
    pf.merges, pf.conflicts = merge_clean(repo, branch, base)
    return pf


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Contributor preflight: is a branch something the Knots "
                    "assembler can replay?")
    ap.add_argument("-C", "--repo", default=".", help="git repo path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight",
                        help="check a branch for poison + clean merge onto its base")
    pf.add_argument("--branch", required=True, help="your feature branch")
    pf.add_argument("--base", required=True,
                    help="the base it targets (a release tag or the dev branch)")
    pf.add_argument("--upstream", default="master",
                    help="upstream ref you must not merge in (default: master)")

    args = ap.parse_args()
    if not _is_repo(args.repo):
        sys.exit(f"not a git repo: {args.repo}")
    for ref in (args.branch, args.base):
        if _rev_parse(args.repo, ref) is None:
            sys.exit(f"ref not found: {ref}")

    result = preflight(args.repo, args.branch, args.base, args.upstream)
    print(f"preflight: {args.branch} onto {args.base}")
    print(result.report())
    sys.exit(0 if result.ready else 1)


if __name__ == "__main__":
    _main()
