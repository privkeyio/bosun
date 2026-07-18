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
from bosun.github import resolve_pr


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


def fetch_pr_head(repo, pr_token, remote_url=None) -> tuple[str, str]:
    """Fetch a PR's head commit into `repo` and return (sha, label).

    Uses plain git against refs/pull/<n>/head, so it needs no API token and works
    even if the contributor has no remotes set up for that fork. `remote_url`
    overrides the derived GitHub URL (used by the tests to stay offline)."""
    r = resolve_pr(pr_token)
    if r is None:
        raise ValueError(f"not a PR token: {pr_token!r} (expected e.g. 34093, k292, g899)")
    gh_repo, num = r
    url = remote_url or f"https://github.com/{gh_repo}"
    res = _git(repo, "fetch", "--quiet", url, f"refs/pull/{num}/head", check=False)
    if res.returncode != 0:
        raise RuntimeError(f"could not fetch {gh_repo}#{num}: "
                           f"{(res.stdout or '').strip() or 'fetch failed'}")
    sha = _rev_parse(repo, "FETCH_HEAD")
    if not sha:
        raise RuntimeError(f"fetched {gh_repo}#{num} but FETCH_HEAD did not resolve")
    return sha, f"{gh_repo}#{num}"


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


def preflight_all(repo, base, upstream="master", prs=None,
                  gh_repo="bitcoinknots/bitcoin", prefix="k", remote_url=None):
    """Preflight a set of PRs against one base. Yields a result dict per PR.

    `prs` is a list of PR numbers; if None they are fetched from GitHub (open,
    non-draft). A PR that cannot be fetched is reported rather than aborting the
    run, so one dead ref does not kill a batch."""
    if prs is None:
        from bosun.github import list_open_prs
        prs = [p["num"] for p in list_open_prs(gh_repo)]
    for num in prs:
        token = f"{prefix}{num}"
        row = {"pr": token, "repo": gh_repo, "num": num}
        try:
            sha, label = fetch_pr_head(repo, token, remote_url)
        except (ValueError, RuntimeError) as e:
            row.update(error=str(e), ready=False)
            yield row
            continue
        r = preflight(repo, sha, base, upstream)
        row.update(label=label, ready=r.ready, poisoned=r.poisoned,
                   poison=r.poison, clean=r.clean, conflicts=r.conflicts,
                   upstream_absent=r.upstream_absent)
        yield row


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Contributor preflight: is a branch something the Knots "
                    "assembler can replay?")
    ap.add_argument("-C", "--repo", default=".", help="git repo path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight",
                        help="check a branch for poison + clean merge onto its base")
    who = pf.add_mutually_exclusive_group(required=True)
    who.add_argument("--branch", help="your feature branch (a local ref)")
    who.add_argument("--pr", help="a PR to fetch and check instead, e.g. k292, g899, 34093")
    pf.add_argument("--base", required=True,
                    help="the base it targets (a release tag or the dev branch)")
    pf.add_argument("--upstream", default="master",
                    help="upstream ref you must not merge in (default: master)")
    pf.add_argument("--pr-url", dest="pr_url",
                    help="override the git URL to fetch the PR from")

    pa = sub.add_parser("preflight-all",
                        help="preflight every open PR against one base")
    pa.add_argument("--base", required=True, help="the base they target")
    pa.add_argument("--upstream", default="master",
                    help="upstream ref they must not merge in (default: master)")
    pa.add_argument("--gh-repo", dest="gh_repo", default="bitcoinknots/bitcoin",
                    help="repo to list open PRs from (default: bitcoinknots/bitcoin)")
    pa.add_argument("--prefix", default="k",
                    help="PR token prefix for that repo (default: k)")
    pa.add_argument("--prs", help="comma-separated PR numbers instead of listing open ones")
    pa.add_argument("--pr-url", dest="pr_url",
                    help="override the git URL to fetch PRs from")
    pa.add_argument("--json", dest="json_out", help="also write results as JSON here")

    args = ap.parse_args()
    if not _is_repo(args.repo):
        sys.exit(f"not a git repo: {args.repo}")

    if args.cmd == "preflight-all":
        if _rev_parse(args.repo, args.base) is None:
            sys.exit(f"ref not found: {args.base}")
        nums = [int(n) for n in args.prs.split(",")] if args.prs else None
        rows = []
        print(f"preflight-all: open PRs onto {args.base}")
        for row in preflight_all(args.repo, args.base, args.upstream, nums,
                                 args.gh_repo, args.prefix, args.pr_url):
            rows.append(row)
            if row.get("error"):
                print(f"  ? {row['pr']}: {row['error']}")
            elif row["ready"]:
                print(f"  ✓ {row['pr']}: ready")
            else:
                why = []
                if row.get("poisoned"):
                    why.append(f"poisoned ({row['poison'][:10]})")
                if not row.get("clean"):
                    why.append("conflicts: " + (", ".join(row["conflicts"]) or "merge failed"))
                if row.get("upstream_absent"):
                    why.append("upstream ref missing")
                print(f"  ✗ {row['pr']}: {'; '.join(why)}")
        ready = sum(1 for r in rows if r.get("ready"))
        print(f"{ready}/{len(rows)} ready")
        if args.json_out:
            import json
            with open(args.json_out, "w") as f:
                json.dump(rows, f, indent=1)
            print(f"wrote {args.json_out}")
        sys.exit(0 if ready == len(rows) else 1)

    branch, label = args.branch, args.branch
    if args.pr:
        try:
            branch, label = fetch_pr_head(args.repo, args.pr, args.pr_url)
        except (ValueError, RuntimeError) as e:
            sys.exit(str(e))
    for ref in (branch, args.base):
        if _rev_parse(args.repo, ref) is None:
            sys.exit(f"ref not found: {ref}")

    result = preflight(args.repo, branch, args.base, args.upstream)
    print(f"preflight: {label} onto {args.base}")
    print(result.report())
    sys.exit(0 if result.ready else 1)


if __name__ == "__main__":
    _main()
