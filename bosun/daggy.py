"""Daggy-fix helper for the traditional-git Knots model.

Two pieces, matching the agreed workflow (develop the fix on master, rebase it
backward to the oldest affected commit, then merge forward):

  find     Locate the bug-introducing commit via `git bisect run` driven by a
           regression test — the answer to "how far back do I rebase?", the one
           genuinely hard/manual step. Read-only: it only identifies a commit.

  forward  Dry-run whether the fix merges cleanly into each live branch
           (oldest -> newest), using throwaway worktrees so the repo is untouched.

The merging itself is left to plain git; this automates the parts that aren't
obvious or are tedious to repeat.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile


def _git(repo, *args, check=True, capture=True):
    return subprocess.run(["git", "-C", repo, *args], text=True, check=check,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)


def _is_repo(repo) -> bool:
    return subprocess.run(["git", "-C", repo, "rev-parse", "--git-dir"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _is_ancestor(repo, a, b) -> bool:
    return subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", a, b],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def find(repo, good, bad, test_cmd, test_paths, fix_branch) -> str | None:
    """Bisect between `good` (test passes) and `bad` (test fails) to find the
    first commit where the regression test starts failing. Returns its SHA."""
    inject = ""
    cleanup = ""
    if test_paths:
        paths = " ".join(test_paths)
        ref = fix_branch or bad
        inject = f'git checkout {ref} -- {paths} 2>/dev/null\n'
        cleanup = (f'git checkout HEAD -- {paths} 2>/dev/null\n'
                   f'git clean -fdq -- {paths} 2>/dev/null\n')
    # git bisect run: exit 0 = good (bug absent), 1-127 (except 125) = bad.
    script = (f"#!/bin/sh\n{inject}{test_cmd}\nrc=$?\n{cleanup}exit $rc\n")

    fd, path = tempfile.mkstemp(suffix=".sh", prefix="bosun-bisect-")
    os.write(fd, script.encode())
    os.close(fd)
    os.chmod(path, 0o755)
    try:
        subprocess.run(["git", "-C", repo, "bisect", "reset"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _git(repo, "bisect", "start", bad, good)
        run = _git(repo, "bisect", "run", path, check=False)
        sys.stderr.write(run.stdout or "")
        m = re.search(r"([0-9a-f]{7,40}) is the first bad commit", run.stdout or "")
        return m.group(1) if m else None
    finally:
        subprocess.run(["git", "-C", repo, "bisect", "reset"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.unlink(path)


def merge_clean(repo, fix, branch) -> tuple[bool, list[str]]:
    """Does `fix` merge cleanly into `branch`? Tested in a throwaway worktree;
    the repo's working tree is never touched. Returns (clean, conflicted_files)."""
    wt = tempfile.mkdtemp(prefix="bosun-wt-")
    try:
        _git(repo, "worktree", "add", "--detach", "--quiet", wt, branch)
        merged = subprocess.run(["git", "-C", wt, "merge", "--no-commit", "--no-ff", fix],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        conflicts = _git(wt, "diff", "--name-only", "--diff-filter=U").stdout.split()
        subprocess.run(["git", "-C", wt, "merge", "--abort"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return (merged.returncode == 0 and not conflicts, conflicts)
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Daggy-fix helper (find rebase floor; check forward merges).")
    ap.add_argument("-C", "--repo", default=".", help="git repo path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="bisect to the bug-introducing commit (the rebase floor)")
    f.add_argument("--good", required=True, help="ref where the test PASSES (bug absent)")
    f.add_argument("--bad", default="HEAD", help="ref where the test FAILS (bug present)")
    f.add_argument("--test", required=True, help="shell command; exit 0 = bug absent")
    f.add_argument("--test-paths", nargs="*", help="paths to check out from --fix-branch at each step (inject the new test)")
    f.add_argument("--fix-branch", help="branch holding the regression test (default: --bad)")

    fw = sub.add_parser("forward", help="dry-run whether the fix merges cleanly into each branch")
    fw.add_argument("--fix", required=True, help="the fix ref to merge forward")
    fw.add_argument("--branches", nargs="+", required=True, help="target branches, oldest -> newest")

    args = ap.parse_args()
    if not _is_repo(args.repo):
        sys.exit(f"not a git repo: {args.repo}")

    if args.cmd == "find":
        if not _is_ancestor(args.repo, args.good, args.bad):
            sys.exit(f"--good ({args.good}) is not an ancestor of --bad ({args.bad}); "
                     "bisect needs a linear good->bad range. Pick a --good that is a true "
                     "ancestor of --bad (assembled release tags often aren't).")
        sha = find(args.repo, args.good, args.bad, args.test, args.test_paths, args.fix_branch)
        if not sha:
            sys.exit("could not determine the bug-introducing commit (check --good/--bad and the test)")
        subj = _git(args.repo, "log", "-1", "--format=%h %s", sha).stdout.strip()
        print(f"\nbug introduced at: {subj}")
        print(f"rebase floor:      {sha}")
        print(f"  rebase your fix onto this commit, then merge forward.")
    elif args.cmd == "forward":
        print(f"merge-forward dry-run for {args.fix}:")
        for b in args.branches:
            clean, conflicts = merge_clean(args.repo, args.fix, b)
            if clean:
                print(f"  ✓ {b}: clean")
            else:
                print(f"  ✗ {b}: conflicts in {', '.join(conflicts) or '(merge failed)'}")


if __name__ == "__main__":
    _main()
