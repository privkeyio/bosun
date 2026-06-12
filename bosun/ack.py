"""Review-signal detection from PR comment text.

This is the GitHub side of bosun: turning raw PR comments into a coarse review
level. The classifier is adapted from Pierre Rochard's bitcoin-acks
(MIT) ``identify_review_decision``, kept deliberately simple. It feeds the
0-3 review level the spec's freeform ``Needs review`` tags only gesture at.
"""

from __future__ import annotations

from enum import IntEnum


class ReviewSignal(IntEnum):
    NONE = 0
    CONCEPT_ACK = 1
    UNTESTED_ACK = 2
    TESTED_ACK = 3
    NACK = -1


def classify_comment(text: str) -> ReviewSignal:
    t = text.strip().lower()
    if "nack" in t and "ack" not in t.replace("nack", ""):
        return ReviewSignal.NACK
    if "concept ack" in t or "re-ack" in t or "reack" in t:
        return ReviewSignal.CONCEPT_ACK
    if "tested ack" in t or t.startswith("tack ") or "tested-ack" in t:
        return ReviewSignal.TESTED_ACK
    if "utack" in t or "untested ack" in t:
        return ReviewSignal.UNTESTED_ACK
    if t.startswith("ack ") or t.startswith("ack\n") or t == "ack":
        return ReviewSignal.TESTED_ACK
    return ReviewSignal.NONE


def review_level(signals: list[ReviewSignal]) -> int:
    """Reduce a PR's comment signals to a 0-3 review level.

    0 none, 1 low (concept only), 2 medium (>=1 utACK or >=2 concept), 3 high
    (>=1 tested ACK or >=2 utACK). A NACK is surfaced separately, not folded in.
    """
    tested = sum(s == ReviewSignal.TESTED_ACK for s in signals)
    utacks = sum(s == ReviewSignal.UNTESTED_ACK for s in signals)
    concepts = sum(s == ReviewSignal.CONCEPT_ACK for s in signals)
    if tested or utacks >= 2:
        return 3
    if utacks or concepts >= 2:
        return 2
    if concepts:
        return 1
    return 0
