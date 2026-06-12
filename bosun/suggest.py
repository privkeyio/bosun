"""Turn enriched spec entries into actionable maintenance suggestions.

Operates on the enriched entry dicts the web layer builds (spec fields + cached
GitHub status). Categorizes candidates by what a maintainer would likely do, and
can emit a unified diff that removes the stale candidate lines from the spec, so
the analysis becomes a reviewable patch rather than just a dashboard.
"""

from __future__ import annotations

import difflib
from datetime import datetime, timezone

STALE_DAYS = 365


def _age_days(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def categorize(entries: list[dict]) -> dict:
    """Group commented-out candidates by suggested action.

    Only candidates whose PR status has been fetched can be categorized; the
    counts report how much of the candidate set that covers.
    """
    cand = [e for e in entries if e.get("kind") == "merge" and not e.get("active")]
    known = [e for e in cand if e.get("pr_state")]

    def by(pred):
        return [e for e in known if pred(e)]

    return {
        "merged_upstream": by(lambda e: e["pr_state"] == "merged"),
        "closed_upstream": by(lambda e: e["pr_state"] == "closed"),
        "ready": by(lambda e: e["pr_state"] == "open"
                    and (e.get("review_level") or 0) >= 2 and not e.get("nacks")),
        "contested": by(lambda e: e.get("nacks")),
        "stale": by(lambda e: e["pr_state"] == "open"
                    and _age_days(e.get("updated_at")) > STALE_DAYS),
        "known": len(known),
        "total": len(cand),
    }


# Categories whose lines are safe-ish to remove as spec hygiene (no longer open
# upstream). Keyed by the short name used in the ?include= query.
REMOVABLE = {"merged": "merged_upstream", "closed": "closed_upstream"}


def cleanup_diff(spec_text: str, linenos: set[int], fname: str) -> str:
    """Unified diff of the spec with the given 1-based line numbers removed."""
    orig = spec_text.splitlines(keepends=True)
    kept = [ln for i, ln in enumerate(orig, 1) if i not in linenos]
    return "".join(difflib.unified_diff(orig, kept, fromfile=f"a/{fname}", tofile=f"b/{fname}"))
