"""Load spec files from a GitHub repo/branch.

Default source is luke-jr/tmp @ knots-spec (the canonical Knots spec repo).
Point it at any fork/branch to browse your own specs. Listing uses the GitHub
API (1 request, honours GITHUB_TOKEN for rate limits); fetching raw spec
content uses raw.githubusercontent.com (no API limit).
"""

from __future__ import annotations

import json
import os
import urllib.request

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"

DEFAULT_REPO = "luke-jr/tmp"
DEFAULT_REF = "knots-spec"


def _get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "bosun"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def list_specs(repo: str, ref: str) -> list[str]:
    """Return paths of all *.spec files in repo@ref, sorted."""
    data = json.loads(_get(f"{API}/repos/{repo}/git/trees/{ref}?recursive=1",
                           "application/vnd.github+json"))
    return sorted(e["path"] for e in data.get("tree", [])
                  if e.get("type") == "blob" and e["path"].endswith(".spec"))


def fetch_spec(repo: str, ref: str, path: str) -> str:
    return _get(f"{RAW}/{repo}/{ref}/{path}", "text/plain").decode("utf-8")
