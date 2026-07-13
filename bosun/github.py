"""Fetch live PR status (state + ACK level) from GitHub, with on-disk caching.

Pure stdlib. Resolves a spec PR token to its source repo (numeric ->
bitcoin/bitcoin, k### -> bitcoinknots/bitcoin, g### -> bitcoin-core/gui),
fetches the PR's state and comments, and derives a 0-3 review level via
``ack``. Results are cached under ``.bosun-cache`` with a TTL so the web app
and repeated runs stay cheap and rate-limit friendly.

Auth: uses ``GITHUB_TOKEN`` if set, else falls back to ``gh auth token``.
Without either, the unauthenticated limit is 60 requests/hour.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .ack import ReviewSignal, classify_comment, review_level

API = "https://api.github.com"
PR_REPO_BY_PREFIX = {"": "bitcoin/bitcoin", "k": "bitcoinknots/bitcoin", "g": "bitcoin-core/gui"}
CACHE_DIR = Path(os.environ.get("BOSUN_CACHE", ".bosun-cache"))
CACHE_TTL = int(os.environ.get("BOSUN_CACHE_TTL", str(24 * 3600)))
CACHE_VERSION = 2  # bump to invalidate cached entries with an older schema

_token_cache: str | None = None


class RateLimited(Exception):
    pass


def resolve_pr(prnum: str | None) -> tuple[str, int] | None:
    """Map a spec PR token to (repo, number), or None if it isn't a PR ref."""
    if not prnum:
        return None
    m = re.match(r"^([A-Za-z]?)(\d+)$", prnum)
    if not m:
        return None
    repo = PR_REPO_BY_PREFIX.get(m.group(1).lower())
    return (repo, int(m.group(2))) if repo else None


def pr_url(prnum: str | None) -> str | None:
    r = resolve_pr(prnum)
    return f"https://github.com/{r[0]}/pull/{r[1]}" if r else None


def list_open_prs(repo: str) -> list[dict]:
    """All open (non-draft) PRs in repo, slimmed to what the UI needs. One API
    call per 100 PRs; honours GITHUB_TOKEN for rate limits. May raise RateLimited."""
    out: list[dict] = []
    page = 1
    while True:
        prs = _get(f"{API}/repos/{repo}/pulls?state=open&per_page=100&page={page}")
        for pr in prs:
            if pr.get("draft"):
                continue
            out.append({
                "num": pr["number"],
                "title": pr.get("title"),
                "updated_at": pr.get("updated_at"),
                "labels": [lb["name"] for lb in pr.get("labels", [])],
            })
        if len(prs) < 100:
            break
        page += 1
    return out


def _token() -> str | None:
    global _token_cache
    if _token_cache is not None:
        return _token_cache or None
    tok = os.environ.get("GITHUB_TOKEN", "")
    if not tok:
        try:
            tok = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            tok = ""
    _token_cache = tok
    return tok or None


def _get(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "bosun"})
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise RateLimited(f"rate limit hit; resets at {e.headers.get('X-RateLimit-Reset')}")
        raise


def _cache_path(repo: str, num: int) -> Path:
    return CACHE_DIR / repo / f"{num}.json"


# PR states that never change once reached — safe to reuse past the cache TTL
# rather than re-fetching. (A reopened PR is rare and self-heals on a manual refresh.)
_TERMINAL = ("merged", "closed", "missing")


def _read_cache_raw(repo: str, num: int) -> dict | None:
    """Cached entry ignoring TTL (schema-version checked). None if absent/stale-schema."""
    p = _cache_path(repo, num)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return data if data.get("v") == CACHE_VERSION else None


def _read_cache(repo: str, num: int) -> dict | None:
    p = _cache_path(repo, num)
    if p.exists() and (time.time() - p.stat().st_mtime) < CACHE_TTL:
        return _read_cache_raw(repo, num)
    return None


def pr_status(repo: str, num: int, refresh: bool = False) -> dict:
    """Return cached-or-fetched status for a PR. May raise RateLimited."""
    if not refresh:
        cached = _read_cache(repo, num)
        if cached is not None:
            return cached
        # Terminal state past its TTL: reuse it (touch mtime to keep it display-fresh)
        # instead of spending an API call — most spec PRs are already merged upstream.
        stale = _read_cache_raw(repo, num)
        if stale and stale.get("state") in _TERMINAL:
            _write_cache(repo, num, stale)
            return stale

    try:
        pr = _get(f"{API}/repos/{repo}/pulls/{num}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            data = {"v": CACHE_VERSION, "repo": repo, "num": num, "state": "missing"}
            _write_cache(repo, num, data)
            return data
        raise

    author = (pr.get("user") or {}).get("login")
    by_author: dict[str, ReviewSignal] = {}

    # Top-level issue comments (where most Bitcoin ACKs live).
    page = 1
    while True:
        comments = _get(f"{API}/repos/{repo}/issues/{num}/comments?per_page=100&page={page}")
        for c in comments:
            sig = classify_comment(c.get("body") or "")
            if sig != ReviewSignal.NONE:
                by_author[(c.get("user") or {}).get("login")] = sig
        if len(comments) < 100:
            break
        page += 1

    # Formal PR reviews: parse the body, and treat a bare APPROVE as a utACK.
    page = 1
    while True:
        reviews = _get(f"{API}/repos/{repo}/pulls/{num}/reviews?per_page=100&page={page}")
        for rv in reviews:
            sig = classify_comment(rv.get("body") or "")
            if sig == ReviewSignal.NONE and rv.get("state") == "APPROVED":
                sig = ReviewSignal.UNTESTED_ACK
            if sig != ReviewSignal.NONE:
                by_author[(rv.get("user") or {}).get("login")] = sig
        if len(reviews) < 100:
            break
        page += 1

    by_author.pop(author, None)  # ignore self-ACKs

    acks = [s for s in by_author.values() if s > 0]
    data = {
        "v": CACHE_VERSION,
        "repo": repo, "num": num,
        "state": "merged" if pr.get("merged_at") else pr.get("state"),
        "merged": bool(pr.get("merged_at")),
        "review_level": review_level(acks),
        "acks": len(acks),
        "nacks": sum(1 for s in by_author.values() if s == ReviewSignal.NACK),
        "title": pr.get("title"),
        "updated_at": pr.get("updated_at"),
        "fetched": int(time.time()),
    }
    _write_cache(repo, num, data)
    return data


def _write_cache(repo: str, num: int, data: dict) -> None:
    p = _cache_path(repo, num)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def _main() -> None:
    import argparse
    import collections
    from . import source
    from .spec import parse_spec

    ap = argparse.ArgumentParser(description="Ingest PR status for a spec into the cache.")
    ap.add_argument("--repo", default=source.DEFAULT_REPO)
    ap.add_argument("--ref", default=source.DEFAULT_REF)
    ap.add_argument("--file", required=True, help="spec file path within the repo")
    ap.add_argument("--limit", type=int, default=0, help="max PRs to fetch (0 = all)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache TTL")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between API calls")
    args = ap.parse_args()

    entries = parse_spec(source.fetch_spec(args.repo, args.ref, args.file))
    prs, seen = [], set()
    for e in entries:
        r = resolve_pr(e.prnum)
        if r and r not in seen:
            seen.add(r)
            prs.append(r)
    if args.limit:
        prs = prs[: args.limit]

    print(f"{'authenticated' if _token() else 'UNAUTHENTICATED (60/hr)'}; "
          f"{len(prs)} unique PRs referenced")
    states, fetched = collections.Counter(), 0
    try:
        for i, (repo, num) in enumerate(prs, 1):
            cached = _read_cache(repo, num) is not None and not args.refresh
            d = pr_status(repo, num, refresh=args.refresh)
            states[d.get("state")] += 1
            if not cached:
                fetched += 1
                if args.sleep:
                    time.sleep(args.sleep)
            if i % 25 == 0 or i == len(prs):
                print(f"  {i}/{len(prs)} ({fetched} fetched)")
    except RateLimited as e:
        print(f"stopped: {e}\n  fetched {fetched} before limit; rerun later to continue")

    print("states:", dict(states))


if __name__ == "__main__":
    _main()
