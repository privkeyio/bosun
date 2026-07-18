# bosun

Track PR review and triage status across Bitcoin forks.

Bitcoin Knots' review/triage state lives as freeform comments in its assembly
spec (`# Needs review:`, `# Triage:`, `# Broken:` ...). bosun parses that into a
queryable view and pairs it with live PR state and review level from GitHub, so
you can see at a glance where each PR stands across `bitcoin/bitcoin`,
`bitcoin-core/gui`, `bitcoinknots/bitcoin`, and any fork.

The core (`spec` / `source` / `github` / `ack` / `suggest` / `report` / `daggy` /
`contributor`) is pure stdlib; only the web UI needs Flask.

Live instance: <https://bosun.privkey.io>

## Web app

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m bosun.web            # http://127.0.0.1:8765
.venv/bin/python -m bosun.web --repo me/tmp --ref my-specs   # default a fork
```

Pick a spec from the dropdown (defaults to
[`luke-jr/tmp` @ `knots-spec`](https://github.com/luke-jr/tmp/tree/knots-spec)), or
choose **★ open Knots PRs** to triage every open PR in `bitcoinknots/bitcoin`,
including ones not yet in any spec. Filter by source (Core/Knots/GUI), GitHub
labels, review level, or the **ready** quick-filter (open + tested ACK, no NACK);
sort by any column; and **fetch GitHub status (shown)** to pull live PR state and
the 0-3 review level for the visible rows. Or set `repo`/`ref` to browse your own
fork.

Auth uses `GITHUB_TOKEN`, falling back to `gh auth token`; without either the
GitHub limit is 60 requests/hour. Bulk-prefetch a whole spec into the cache:

```bash
.venv/bin/python -m bosun.github --file knots-next-29.spec
```

## Hosted snapshot (GitHub Pages)

GitHub Pages can't run the Flask app (no server), so `bosun.static_build` bakes a
static snapshot: it reuses the same frontend and swaps the live `/api` calls for
pre-generated JSON files. A scheduled Action ingests PR status and publishes to
Pages, so visitors need no token.

```bash
.venv/bin/python -m bosun.static_build --ingest -o public   # build the snapshot
python3 -m http.server -d public 8000                       # preview at :8000
```

Deploy is via `.github/workflows/deploy.yml` (push, daily cron, manual dispatch).
The open-Knots-PRs view is baked automatically; add more published specs in
`SPECS` in `bosun/static_build.py`.

## Maintenance digest (markdown, for the terminal)

A one-command summary of what to act on — ready-to-promote shortlist (ranked by
ACKs), contested PRs, and dead candidates — from the cached status above:

```bash
python3 -m bosun.report --file knots-next-29.spec          # prints markdown
python3 -m bosun.report --file knots-next-29.spec -o digest.md
```

## Daggy-fix helper (for the traditional-git model)

For the [proposed DAG-native Knots model](https://gist.github.com/chrisguida/65337b84ffb4acbd09aa5ba073b55d00),
the core operation is: develop a fix on master, rebase it back to the oldest
affected commit, then merge it forward into each live branch. This automates the
two parts that aren't trivial:

```bash
# Where do I rebase back to? Bisect to the bug-introducing commit using a
# regression test (exit 0 = bug absent). --test-paths injects a new test file
# from the fix branch at each step.
python3 -m bosun.daggy -C /path/to/knots find \
    --good v27.0 --bad master --test "ctest -R my_regression" \
    --fix-branch my-fix --test-paths src/test/foo_tests.cpp

# Does the fix merge cleanly into each live branch? (dry-run, throwaway worktrees)
python3 -m bosun.daggy -C /path/to/knots forward --fix my-fix --branches 29.x 30.x master
```

`find` is read-only (it only identifies a commit); `forward` never touches the
working tree. The merging itself is left to plain git.

See it work on a synthetic repo (no network, no Core build):

```bash
python3 tests/test_daggy.py
```

## Contributor preflight (will the assembler accept my branch?)

Knots is not merged, it is assembled: a release replays a spec that checks out a
base and merges a curated set of branches on top. A change only lands if its
branch is something the assembler can replay, so this checks that before you ask
a maintainer to add it, catching the two things the assembler hard-rejects:

```bash
python3 -m bosun.contributor -C /path/to/knots preflight \
    --branch my-fix --base v29.3.knots20260508 --upstream master

# or check any PR by number. This fetches refs/pull/<n>/head straight over git,
# so it needs no API token and no remotes configured for that fork.
# (k = bitcoinknots/bitcoin, g = bitcoin-core/gui, bare number = bitcoin/bitcoin)
python3 -m bosun.contributor -C /path/to/knots preflight \
    --pr k292 --base v29.3.knots20260508 --upstream master
```

- **poison**: an upstream branch merged *into* yours. The assembler dies
  `Branch <x> is poisoned`. Fix: rebase onto the base, do not merge upstream in.
- **conflict**: your branch does not merge cleanly onto the base, so someone
  would have to hand-maintain a resolution diff.

It prints READY / NOT READY with the fix for each and exits 0/1, so it is usable
in a script or CI. Read-only: the merge test runs in a throwaway worktree, so
your working tree is never touched.

The same check runs in batch over every open PR, which answers the maintainer's
question of which ones will not assemble onto the next base:

```bash
python3 -m bosun.contributor -C /path/to/knots preflight-all \
    --base v29.3.knots20260508 --upstream master --json preflight.json
```

One line per PR plus an `N/M ready` summary; a PR that cannot be fetched is
reported and the batch continues. `--json` writes the structured results, and
`--prs 292,297` checks an explicit set instead of listing open ones.

```bash
python3 tests/test_contributor.py
```

## CLI (pure stdlib, no install)

```bash
python3 -m bosun.spec testdata/knots-next-29.spec --summary
python3 -m bosun.spec testdata/knots-next-29.spec --norm needs-review
python3 -m bosun.spec testdata/knots-next-29.spec --json
```

## License

MIT. See [LICENSE](LICENSE). The ACK classifier in `bosun/ack.py` is adapted
from Pierre Rochard's [bitcoin-acks](https://github.com/PierreRochard/bitcoin-acks) (MIT).
