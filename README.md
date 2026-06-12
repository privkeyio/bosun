# bosun

Track PR review and triage status across Bitcoin forks.

Bitcoin Knots' review/triage state currently lives only as freeform comments in
the assembly spec (`# Needs review:`, `# Triage:`, `# Broken:` ...), and there's
no machine-readable view of where a given PR stands across `bitcoin/bitcoin`,
`bitcoin-core/gui`, `bitcoinknots/bitcoin`, and downstream forks. bosun is the
beginning of that view: a normalized, queryable picture of what each fork
carries and how far along its review is.

## Status: early prototype

The core (`spec` / `source` / `ack`) is pure stdlib; only the web UI needs Flask.

- **`bosun/spec.py`** — parses a Knots assembly spec into structured
  `SpecEntry` records (section, active vs commented-out candidate, disposition
  tag, PR number, branch, commit/`last=` pins, upstream) and normalizes the
  ~200 freeform disposition strings into canonical buckets (`needs-review`,
  `needs-concept`, `needs-work`, `triage`, `deferred`, `wontfix`, ...).
- **`bosun/source.py`** — lists and fetches spec files from a GitHub repo/branch
  (default `luke-jr/tmp` @ `knots-spec`). Honours `GITHUB_TOKEN` for rate limits.
- **`bosun/ack.py`** — classifies PR comment text into review signals
  (concept / utACK / tested-ACK / NACK) and reduces a PR's signals to a 0-3
  review level. Adapted from Pierre Rochard's bitcoin-acks (MIT).
- **`bosun/web.py`** — a Flask app: pick any spec from the default repo, or
  point `repo`/`ref` at your own fork. Sortable, filterable table with canonical
  status buckets and PR numbers linked to the right fork's GitHub.

## Usage

### Web app (pick specs from any repo/fork)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m bosun.web                 # http://127.0.0.1:8765

# default a different fork as the source
.venv/bin/python -m bosun.web --repo me/tmp --ref my-specs
```

Open the page, pick a spec from the dropdown (defaults to `luke-jr/tmp` @
`knots-spec`), or change `repo`/`ref` to browse your own fork's specs. Set
`GITHUB_TOKEN` in the environment to raise the API rate limit.

### CLI (pure stdlib, no install)

```bash
# Summary: active vs candidate merges, by section and canonical bucket
python3 -m bosun.spec testdata/knots-next-29.spec --summary

# Candidates in a given bucket
python3 -m bosun.spec testdata/knots-next-29.spec --norm needs-review

# Structured dump
python3 -m bosun.spec testdata/knots-next-29.spec --json
```

## Roadmap

1. **Status normalization** — the real spec has ~200 distinct freeform
   disposition strings; map them to a small canonical enum
   (needs-concept / needs-review / needs-work / triage / wontfix / deferred).
2. **GitHub ingestion** — pull PRs + comments for the tracked repos and derive
   the 0-3 review level via `ack.py` (reference: bitcoin-acks GraphQL queries).
3. **Reconcile spec + GitHub** — the spec is the curated triage state; GitHub
   is the raw review signal. The value is merging them.
4. **Cross-fork matrix** — same PR/patch, its review + merge status across
   every tracked fork. The "compare a variety of forks" view.
5. **Persistence + richer UI** — a store behind the viewer and a fuller
   dashboard (the current `web.py` is a read-only, spec-only starting point).

## License

MIT. See [LICENSE](LICENSE).
