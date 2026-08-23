"""Aggregate per-case grading into reportable metrics.

Two rules this module exists to enforce:

1. **No aggregate without its bucket breakout.** An aggregate F1 of 0.88 hiding 0.55 on
   adversarial cases is worse than useless -- it is a false assurance, which is the
   exact failure mode evals exist to prevent. `Report.aggregate` is deliberately not
   reachable without `Report.by_bucket` alongside it.
2. **No point estimate without an interval.** The spike measured a macro-F1 noise floor
   of 0.40 at n=5. At the real n=35 test split, bucket-level F1 still rests on 3-15
   cases. Reporting `0.88` instead of `0.88 [0.74-0.96]` invites conclusions the sample
   size cannot support.

Bootstrap resampling is seeded so a committed results file regenerates identical
intervals.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20260822
CI_LEVEL = 0.95


@dataclass
class CaseOutcome:
    """One graded case. Produced by the graders, consumed here."""

    case_id: str
    bucket: str
    schema_valid: bool
    parse_method: str
    precision: float
    recall: float
    f1: float
    n_predicted: int
    n_expected: int
    forbidden_hits: int
    near_misses: int
    evidence_total: int
    evidence_verbatim: int
    evidence_near_verbatim: int
    cost_usd: float = 0.0
    latency_s: float = 0.0


@dataclass
class Interval:
    point: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.point:.2f} [{self.low:.2f}-{self.high:.2f}]"


@dataclass
class BucketMetrics:
    bucket: str
    n: int
    precision: float
    recall: float
    f1: Interval
    schema_validity: float
    forbidden_rate: float
    verbatim_rate: float
    near_verbatim_rate: float
    cost_usd: float
    extractions: int


@dataclass
class Report:
    config_id: str
    aggregate: BucketMetrics
    by_bucket: dict[str, BucketMetrics] = field(default_factory=dict)
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    total_cost: float = 0.0
    parse_methods: dict[str, int] = field(default_factory=dict)

    def worst_bucket(self) -> BucketMetrics | None:
        """The bucket an aggregate would hide. Surface it, always."""
        if not self.by_bucket:
            return None
        return min(self.by_bucket.values(), key=lambda b: b.f1.point)


def bootstrap_ci(
    values: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = CI_LEVEL,
) -> Interval:
    """Percentile bootstrap CI of the mean.

    Seeded: the same values must always produce the same interval, so a committed
    results file regenerates its charts exactly.
    """
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return Interval(0.0, 0.0, 0.0)
    point = float(arr.mean())
    if arr.size == 1:
        return Interval(point, point, point)

    rng = np.random.default_rng(seed)
    draws = rng.choice(arr, size=(resamples, arr.size), replace=True).mean(axis=1)
    tail = (1.0 - level) / 2.0
    return Interval(
        point=point,
        low=float(np.quantile(draws, tail)),
        high=float(np.quantile(draws, 1.0 - tail)),
    )


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), pct))


def _summarize(bucket: str, outcomes: Sequence[CaseOutcome]) -> BucketMetrics:
    n = len(outcomes)
    if n == 0:
        return BucketMetrics(bucket, 0, 0.0, 0.0, Interval(0, 0, 0), 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    extractions = sum(o.n_predicted for o in outcomes)
    forbidden = sum(o.forbidden_hits for o in outcomes)
    ev_total = sum(o.evidence_total for o in outcomes)
    ev_verbatim = sum(o.evidence_verbatim for o in outcomes)
    ev_near = sum(o.evidence_near_verbatim for o in outcomes)

    return BucketMetrics(
        bucket=bucket,
        n=n,
        precision=statistics.mean(o.precision for o in outcomes),
        recall=statistics.mean(o.recall for o in outcomes),
        f1=bootstrap_ci([o.f1 for o in outcomes]),
        schema_validity=sum(o.schema_valid for o in outcomes) / n,
        # Denominated in extractions, not cases: a case with 30 extractions and one
        # forbidden hit is not as bad as a case with one extraction that is forbidden.
        forbidden_rate=(forbidden / extractions) if extractions else 0.0,
        verbatim_rate=(ev_verbatim / ev_total) if ev_total else 1.0,
        near_verbatim_rate=((ev_verbatim + ev_near) / ev_total) if ev_total else 1.0,
        cost_usd=sum(o.cost_usd for o in outcomes),
        extractions=extractions,
    )


def build_report(config_id: str, outcomes: Iterable[CaseOutcome]) -> Report:
    outcomes = list(outcomes)
    buckets: dict[str, list[CaseOutcome]] = {}
    for outcome in outcomes:
        buckets.setdefault(outcome.bucket, []).append(outcome)

    parse_methods: dict[str, int] = {}
    for outcome in outcomes:
        parse_methods[outcome.parse_method] = parse_methods.get(outcome.parse_method, 0) + 1

    latencies = [o.latency_s for o in outcomes if o.latency_s > 0]

    return Report(
        config_id=config_id,
        aggregate=_summarize("ALL", outcomes),
        by_bucket={name: _summarize(name, group) for name, group in sorted(buckets.items())},
        p50_latency=percentile(latencies, 50),
        p95_latency=percentile(latencies, 95),
        total_cost=sum(o.cost_usd for o in outcomes),
        parse_methods=parse_methods,
    )


def exceeds_noise_floor(baseline: float, candidate: float, noise_floor: float,
                        multiple: float = 2.0) -> bool:
    """Is a drop from `baseline` to `candidate` bigger than run-to-run noise?

    The spike measured a macro-F1 spread of 0.40 across three identical runs. Any
    comparison smaller than that is indistinguishable from re-running the same config,
    so a regression claim has to clear the floor by a margin.
    """
    return (baseline - candidate) > (noise_floor * multiple)
