#!/usr/bin/env python3
"""Self-contained demo/test for bosun.contributor — no pytest, no network.

Builds a tiny synthetic repo and drives the real `preflight` CLI through the four
cases it exists to catch:

  clean         a branch off the base with an unrelated change -> READY
  poisoned      a branch with the upstream merged in -> NOT READY (even though the
                merge itself is clean; poison is the blocker, as in the assembler)
  conflict      a branch that does not merge cleanly onto the base -> NOT READY
  upstream gone  --upstream ref missing -> poison unchecked, said clearly

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
    try:
        _build(repo)
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
        ]
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    if all(results):
        print("ALL PASS")
        sys.exit(0)
    print(f"{results.count(False)} FAILURE(S)")
    sys.exit(1)


if __name__ == "__main__":
    main()
