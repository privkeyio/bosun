# bosun

Track PR review and triage status across Bitcoin forks.

Bitcoin Knots' review/triage state currently lives only as freeform comments in
the assembly spec (`# Needs review:`, `# Triage:`, `# Broken:` ...), and there's
no machine-readable view of where a given PR stands across `bitcoin/bitcoin`,
`bitcoin-core/gui`, `bitcoinknots/bitcoin`, and downstream forks. bosun is the
beginning of that view: a normalized, queryable picture of what each fork
carries and how far along its review is.

## Status: early prototype

Three pieces work today:

- **`bosun/spec.py`** — parses a Knots assembly spec into structured
  `SpecEntry` records (section, active vs commented-out candidate, disposition
  tag, PR number, branch, commit/`last=` pins, upstream). This turns Luke's
  freeform comments into data.
- **`bosun/ack.py`** — classifies PR comment text into review signals
  (concept / utACK / tested-ACK / NACK) and reduces a PR's signals to a 0-3
  review level. Adapted from Pierre Rochard's bitcoin-acks (MIT).
- **`bosun/web.py`** — a zero-dependency web viewer: a sortable, filterable
  table of every spec entry, with PR numbers linked to the right fork's GitHub.

## Usage

```bash
# Summary of a spec: active vs candidate merges, by section and disposition
python3 -m bosun.spec testdata/knots-next-29.spec --summary

# Just the commented-out candidates that need review
python3 -m bosun.spec testdata/knots-next-29.spec --candidates --status "needs review"

# Structured dump
python3 -m bosun.spec testdata/knots-next-29.spec --json

# Browse it in a browser (serves at http://127.0.0.1:8765)
python3 -m bosun.web testdata/knots-next-29.spec

# ...or write a standalone HTML file instead of serving
python3 -m bosun.web testdata/knots-next-29.spec -o bosun.html
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
