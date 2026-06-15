#!/usr/bin/env python3
"""Self-contained demo/test for bosun.daggy — no pytest, no network, no Core build.

Builds a tiny synthetic repo with a planted bug + a regression test, then drives
both daggy commands through their real CLI and asserts they do the right thing:

  find     pinpoints the exact bug-introducing commit (the rebase floor)
  forward  reports a clean merge vs a genuine conflict

Run from the repo root:

    python3 tests/test_daggy.py

It prints what each command does and exits non-zero if anything is wrong, so it
doubles as a quick correctness check and a reviewable demonstration.
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


def daggy(repo, *args):
    return subprocess.run([sys.executable, "-m", "bosun.daggy", "-C", repo, *args],
                          text=True, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT).stdout


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


def demo_find() -> bool:
    """`calc` should hold "2"; commit c3 breaks it to "3". The fix branch adds a
    regression test and restores it. find should pinpoint c3."""
    repo = tempfile.mkdtemp(prefix="bosun-daggy-demo-")
    try:
        _init(repo)
        _write(repo, "calc", "2\n")
        c1 = _commit(repo, "c1 baseline (answer=2)")
        _write(repo, "notes", "hello\n"); _commit(repo, "c2 unrelated")
        _write(repo, "calc", "3\n"); bug = _commit(repo, "c3 INTRODUCES BUG (answer=3)")
        _write(repo, "notes", "world\n"); _commit(repo, "c4 unrelated")

        git(repo, "checkout", "-q", "-b", "fix", "master")
        _write(repo, "regress.sh", "#!/bin/sh\ngrep -qx 2 calc\n")  # exit 0 iff answer correct
        _write(repo, "calc", "2\n")                                  # the fix
        _commit(repo, "fix + regression test")
        git(repo, "checkout", "-q", "master")

        print("== find: locate the bug-introducing commit ==")
        out = daggy(repo, "find", "--good", c1, "--bad", "master",
                    "--fix-branch", "fix", "--test-paths", "regress.sh",
                    "--test", "sh regress.sh")
        print(out.strip())
        ok = bug[:12] in out
        print(f"{'PASS' if ok else 'FAIL'}: expected the c3 commit {bug[:12]}\n")
        return ok
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def demo_forward() -> bool:
    """`fix` and `v29` both edit the same line of `f` differently → fix conflicts
    into v29 but merges cleanly into master (which it descends from)."""
    repo = tempfile.mkdtemp(prefix="bosun-daggy-demo-")
    try:
        _init(repo)
        _write(repo, "f", "base\n"); _commit(repo, "base")
        git(repo, "checkout", "-q", "-b", "v29")
        _write(repo, "f", "v29 change\n"); _commit(repo, "v29 edits f")
        git(repo, "checkout", "-q", "master")
        git(repo, "checkout", "-q", "-b", "fix")
        _write(repo, "f", "fix change\n"); _commit(repo, "fix edits f")
        git(repo, "checkout", "-q", "master")

        print("== forward: dry-run merge of the fix into each branch ==")
        out = daggy(repo, "forward", "--fix", "fix", "--branches", "v29", "master")
        print(out.strip())
        ok = ("v29: conflicts" in out) and ("master: clean" in out)
        print(f"{'PASS' if ok else 'FAIL'}: expected v29 conflict + master clean\n")
        return ok
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def demo_not_ancestor() -> bool:
    """If --good isn't an ancestor of --bad (e.g. two assembled release tags),
    bisect can't converge — the tool should say why, clearly, up front."""
    repo = tempfile.mkdtemp(prefix="bosun-daggy-demo-")
    try:
        _init(repo)
        _write(repo, "f", "base\n"); _commit(repo, "base")
        git(repo, "checkout", "-q", "-b", "sidebranch")
        _write(repo, "f", "side\n"); _commit(repo, "side commit")   # not an ancestor of master
        git(repo, "checkout", "-q", "master")
        _write(repo, "f", "main\n"); _commit(repo, "main commit")

        print("== find: --good not an ancestor of --bad (should fail clearly) ==")
        out = daggy(repo, "find", "--good", "sidebranch", "--bad", "master", "--test", "true")
        print(out.strip())
        ok = "is not an ancestor" in out
        print(f"{'PASS' if ok else 'FAIL'}: expected a clear 'not an ancestor' message\n")
        return ok
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main() -> None:
    results = [demo_find(), demo_forward(), demo_not_ancestor()]
    if all(results):
        print("ALL PASS")
        sys.exit(0)
    print(f"{results.count(False)} FAILURE(S)")
    sys.exit(1)


if __name__ == "__main__":
    main()
