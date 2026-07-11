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


def _get(url: str, accept: str, auth: bool = True) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "bosun"})
    token = os.environ.get("GITHUB_TOKEN")
    # raw.githubusercontent.com must be fetched WITHOUT a token: for a repo the
    # token can't access it returns 404, not 401 (e.g. a repo-scoped CI token
    # fetching another owner's public spec). The API call still needs the token.
    if auth and token:
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
    return _get(f"{RAW}/{repo}/{ref}/{path}", "text/plain", auth=False).decode("utf-8")
