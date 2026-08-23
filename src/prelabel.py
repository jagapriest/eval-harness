"""Model-assisted pre-labeling with human adjudication.

The spike found first-pass hand labeling missed 5 of 33 named competitors on one
document (17%, all omissions). Model-proposed candidates plus human accept/reject is
therefore a *correctness* improvement, not only a speed-up -- but it anchors the
labeler, so provenance is recorded on every case and a cold-labeled subset is required
to measure the anchoring effect (US-001).

The adjudication loop is separated from I/O so it can be unit-tested without a TTY and
without touching the API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .graders.schema_grader import grade_schema
from .graders.set_grader import evidence_is_verbatim, evidence_similarity

ACCEPT = {"y", "yes"}
REJECT = {"n", "no"}
DEFER = {"?", "d", "defer"}

NEAR_VERBATIM = 0.95


@dataclass
class Candidate:
    name: str
    evidence: str
    confidence: str
    verbatim: bool = False
    similarity: float = 0.0

    @property
    def evidence_flag(self) -> str:
        if self.verbatim:
            return "verbatim"
        if self.similarity >= NEAR_VERBATIM:
            return f"near ({self.similarity:.2f})"
        return f"UNSUPPORTED ({self.similarity:.2f})"


@dataclass
class Adjudication:
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def decided(self) -> int:
        return len(self.accepted) + len(self.rejected)


def candidates_from_output(raw_text: str, document: str) -> list[Candidate]:
    """Parse a model extraction into candidates, annotated with evidence support."""
    result = grade_schema(raw_text)
    if result.extraction is None:
        return []
    out: list[Candidate] = []
    for comp in result.extraction.competitors:
        verbatim = evidence_is_verbatim(comp.evidence, document)
        out.append(
            Candidate(
                name=comp.name,
                evidence=comp.evidence,
                confidence=comp.confidence.value,
                verbatim=verbatim,
                similarity=1.0 if verbatim else evidence_similarity(comp.evidence, document),
            )
        )
    return out


def adjudicate(
    candidates: Iterable[Candidate],
    prompt_fn: Callable[[Candidate], str],
    clock: Callable[[], float] = time.monotonic,
) -> Adjudication:
    """Walk candidates and record accept / reject / defer.

    `prompt_fn` returns a raw response string per candidate; injecting it keeps this
    testable and keeps terminal handling out of the decision logic. Unrecognized input
    is treated as a defer rather than silently accepted -- a mis-keyed label is worse
    than an unresolved one.
    """
    started = clock()
    result = Adjudication()
    for cand in candidates:
        answer = (prompt_fn(cand) or "").strip().lower()
        if answer in ACCEPT:
            result.accepted.append(cand.name)
        elif answer in REJECT:
            result.rejected.append(cand.name)
        else:
            result.deferred.append(cand.name)
    result.seconds = round(clock() - started, 2)
    return result


def apply_adjudication(
    case_path: Path,
    adj: Adjudication,
    config_id: str,
    model: str,
) -> dict:
    """Merge accepted names into the case's expected list and record provenance.

    Accepted names are unioned, never replace: a case may already carry hand labels,
    and this must not silently drop them.
    """
    case = json.loads(case_path.read_text())
    expected = case["expected"].setdefault("competitors", [])
    for name in adj.accepted:
        if name not in expected:
            expected.append(name)

    case["expected"].setdefault("prelabel", {})
    case["expected"]["prelabel"] = {
        "assisted": True,
        "config_id": config_id,
        "model": model,
        "accepted": adj.accepted,
        "rejected": adj.rejected,
        "deferred": adj.deferred,
        "seconds": adj.seconds,
        "note": (
            "Model-proposed candidates adjudicated by a human. Disclose this in the "
            "writeup; see US-001 for the cold-labeled subset that measures anchoring."
        ),
    }
    case_path.write_text(json.dumps(case, indent=2))
    return case


def record_cost(log_path: Path, case_id: str, adj: Adjudication) -> None:
    """Append per-case adjudication cost -- the input to the labeling-cost estimate."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "case_id": case_id,
        "seconds": adj.seconds,
        "candidates": adj.decided + len(adj.deferred),
        "accepted": len(adj.accepted),
        "rejected": len(adj.rejected),
        "deferred": len(adj.deferred),
        "seconds_per_candidate": (
            round(adj.seconds / (adj.decided + len(adj.deferred)), 2)
            if (adj.decided + len(adj.deferred))
            else 0.0
        ),
    }
    with log_path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def format_candidate(cand: Candidate, index: int, total: int) -> str:
    return (
        f"\n[{index}/{total}] {cand.name}\n"
        f"    confidence: {cand.confidence}\n"
        f"    evidence  : {cand.evidence}\n"
        f"    support   : {cand.evidence_flag}\n"
        f"    accept? [y/n/?] "
    )
