# bosun

Track PR review and triage status across Bitcoin forks.

Bitcoin Knots' review/triage state lives as freeform comments in its assembly
spec (`# Needs review:`, `# Triage:`, `# Broken:` ...). bosun parses that into a
queryable view and pairs it with live PR state and review level from GitHub, so
you can see at a glance where each PR stands across `bitcoin/bitcoin`,
`bitcoin-core/gui`, `bitcoinknots/bitcoin`, and any fork.

The core (`spec` / `source` / `github` / `ack` / `suggest` / `report` / `daggy`)
is pure stdlib; only the web UI needs Flask.

## Web app

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m bosun.web            # http://127.0.0.1:8765
.venv/bin/python -m bosun.web --repo me/tmp --ref my-specs   # default a fork
```

Pick a spec from the dropdown (defaults to `luke-jr/tmp` @ `knots-spec`), or set
`repo`/`ref` to browse your own fork. Click the legend chips to filter by state
or canonical bucket, click column headers to sort, and **fetch GitHub status
(shown)** to pull live PR state + 0-3 review level for the visible rows.

Auth uses `GITHUB_TOKEN`, falling back to `gh auth token`; without either the
GitHub limit is 60 requests/hour. Bulk-prefetch a whole spec into the cache:

```bash
.venv/bin/python -m bosun.github --file knots-next-29.spec
```

## Maintenance digest (markdown, for the terminal)

A one-command summary of what to act on — ready-to-promote shortlist (ranked by
ACKs), contested PRs, and dead candidates — from the cached status above:

```bash
python3 -m bosun.report --file knots-next-29.spec          # prints markdown
python3 -m bosun.report --file knots-next-29.spec -o digest.md
```

## Daggy-fix helper (for the traditional-git model)

For the proposed DAG-native Knots model, the core operation is: develop a fix on
master, rebase it back to the oldest affected commit, then merge it forward into
each live branch. This automates the two parts that aren't trivial:

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

## CLI (pure stdlib, no install)

```bash
python3 -m bosun.spec testdata/knots-next-29.spec --summary
python3 -m bosun.spec testdata/knots-next-29.spec --norm needs-review
python3 -m bosun.spec testdata/knots-next-29.spec --json
```

## License

MIT. See [LICENSE](LICENSE). The ACK classifier in `bosun/ack.py` is adapted
from Pierre Rochard's [bitcoin-acks](https://github.com/PierreRochard/bitcoin-acks) (MIT).
