#!/usr/bin/env python3
"""Self-contained demo/test for bosun.contributor — no pytest, no network.

Builds a tiny synthetic repo and drives the real `preflight` CLI through the four
cases it exists to catch:

  clean         a branch off the base with an unrelated change -> READY
  poisoned      a branch with the upstream merged in -> NOT READY (even though the
                merge itself is clean; poison is the blocker, as in the assembler)
  conflict      a branch that does not merge cleanly onto the base -> NOT READY
  upstream gone  --upstream ref missing -> poison unchecked, said clearly

and the --pr path, which fetches refs/pull/<n>/head straight over git. That is
exercised offline against a synthetic "remote" repo via --pr-url file://..., so
the suite still needs no network.

Run from the repo root:

    python3 tests/test_contributor.py

Prints what each case does and exits non-zero if anything is wrong.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def preflight(repo, *args):
    """Run the real CLI; return (stdout, returncode)."""
    r = subprocess.run([sys.executable, "-m", "bosun.contributor", "-C", repo, *args],
                       text=True, cwd=ROOT, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    return r.stdout, r.returncode


def _init(repo):
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "demo@bosun")
    git(repo, "config", "user.name", "bosun-demo")


def _write(repo, name, content):
    with open(os.path.join(repo, name), "w") as f:
        f.write(content)


def _commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _build(repo):
    """A shared topology:

        A ── C1                (master: A, then an unrelated commit C1)
        └── baseC              (base: A with f edited)
    branches off base/A:
        feat-clean    off base, edits a new file g          -> clean, not poisoned
        feat-poison   off base, then merges master (gets C1) -> poisoned, merge clean
        feat-conflict off A, edits f differently than base   -> conflicts on f
    """
    _init(repo)
    _write(repo, "f", "orig\n"); a = _commit(repo, "A")
    git(repo, "checkout", "-q", "-b", "base", a)
    _write(repo, "f", "BASE\n"); _commit(repo, "base edits f")
    git(repo, "checkout", "-q", "master")
    _write(repo, "other", "x\n"); _commit(repo, "C1 unrelated (master ahead of base)")

    git(repo, "checkout", "-q", "-b", "feat-clean", "base")
    _write(repo, "g", "feature\n"); _commit(repo, "clean feature, new file")

    git(repo, "checkout", "-q", "-b", "feat-poison", "base")
    _write(repo, "h", "feature\n"); _commit(repo, "feature commit")
    git(repo, "merge", "-q", "--no-edit", "master")   # pulls C1 in -> poison

    git(repo, "checkout", "-q", "-b", "feat-conflict", a)
    _write(repo, "f", "FEAT\n"); _commit(repo, "feature edits f, conflicts with base")

    git(repo, "checkout", "-q", "master")


def _build_pr_remote(main_repo, remote):
    """A clone of the main repo that publishes two PR heads the way GitHub does:

        refs/pull/1/head   clean feature off base
        refs/pull/2/head   feature off base with master merged in (poisoned)
    """
    subprocess.run(["git", "clone", "-q", main_repo, remote],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    git(remote, "config", "user.email", "demo@bosun")
    git(remote, "config", "user.name", "bosun-demo")

    git(remote, "checkout", "-q", "-b", "pr-clean", "origin/base")
    _write(remote, "pr1", "clean pr\n"); _commit(remote, "clean PR commit")
    git(remote, "update-ref", "refs/pull/1/head", "HEAD")

    git(remote, "checkout", "-q", "-b", "pr-poison", "origin/base")
    _write(remote, "pr2", "poison pr\n"); _commit(remote, "PR commit")
    git(remote, "merge", "-q", "--no-edit", "origin/master")   # pulls the poison in
    git(remote, "update-ref", "refs/pull/2/head", "HEAD")


def _case(repo, name, args, want_rc, want_substrs) -> bool:
    out, rc = preflight(repo, *args)
    print(f"== {name} ==")
    print(out.strip())
    ok = rc == want_rc and all(s in out for s in want_substrs)
    detail = f"rc={rc} (want {want_rc})"
    print(f"{'PASS' if ok else 'FAIL'}: {detail}\n")
    return ok


def main() -> None:
    repo = tempfile.mkdtemp(prefix="bosun-contrib-test-")
    remote = tempfile.mkdtemp(prefix="bosun-contrib-remote-")
    try:
        _build(repo)
        _build_pr_remote(repo, remote)
        url = f"file://{remote}"
        results = [
            _case(repo, "clean -> READY",
                  ["preflight", "--branch", "feat-clean", "--base", "base"],
                  0, ["✓ no upstream merged in", "merges cleanly", "READY:"]),
            _case(repo, "poisoned (merge clean) -> NOT READY",
                  ["preflight", "--branch", "feat-poison", "--base", "base"],
                  1, ["✗ upstream merged in", "poisoned", "merges cleanly", "NOT READY"]),
            _case(repo, "conflict -> NOT READY",
                  ["preflight", "--branch", "feat-conflict", "--base", "base"],
                  1, ["conflicts with base", "NOT READY"]),
            _case(repo, "upstream ref missing -> said clearly",
                  ["preflight", "--branch", "feat-clean", "--base", "base",
                   "--upstream", "no-such-ref"],
                  1, ["could not check for upstream merges", "NOT READY"]),
            _case(repo, "--pr fetches a clean PR head -> READY",
                  ["preflight", "--pr", "k1", "--pr-url", url, "--base", "base"],
                  0, ["bitcoinknots/bitcoin#1", "✓ no upstream merged in", "READY:"]),
            _case(repo, "--pr fetches a poisoned PR head -> NOT READY",
                  ["preflight", "--pr", "k2", "--pr-url", url, "--base", "base"],
                  1, ["bitcoinknots/bitcoin#2", "✗ upstream merged in", "NOT READY"]),
            _case(repo, "--pr with a non-PR token -> clear error",
                  ["preflight", "--pr", "nope", "--pr-url", url, "--base", "base"],
                  1, ["not a PR token"]),
            _case(repo, "preflight-all batches a set of PRs",
                  ["preflight-all", "--prs", "1,2", "--pr-url", url, "--base", "base"],
                  1, ["✓ k1: ready", "✗ k2: poisoned", "1/2 ready"]),
            _case(repo, "preflight-all reports an unfetchable PR without aborting",
                  ["preflight-all", "--prs", "1,999", "--pr-url", url, "--base", "base"],
                  1, ["✓ k1: ready", "? k999:", "1/2 ready"]),
        ]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(remote, ignore_errors=True)

    if all(results):
        print("ALL PASS")
        sys.exit(0)
    print(f"{results.count(False)} FAILURE(S)")
    sys.exit(1)


if __name__ == "__main__":
    main()
