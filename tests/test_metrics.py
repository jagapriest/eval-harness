"""US-007 -- metrics, bucket breakout, bootstrap CIs."""

from __future__ import annotations

import pytest

from src.metrics import (
    BOOTSTRAP_SEED,
    CaseOutcome,
    bootstrap_ci,
    build_report,
    exceeds_noise_floor,
    percentile,
)


def outcome(case_id="c", bucket="clean", f1=1.0, **kw):
    base = dict(
        case_id=case_id, bucket=bucket, schema_valid=True, parse_method="direct",
        precision=f1, recall=f1, f1=f1, n_predicted=2, n_expected=2,
        forbidden_hits=0, near_misses=0, evidence_total=2, evidence_verbatim=2,
        evidence_near_verbatim=0, cost_usd=0.05, latency_s=8.0,
    )
    base.update(kw)
    return CaseOutcome(**base)


# --------------------------- bootstrap ---------------------------

def test_bootstrap_is_deterministic_for_a_fixed_seed():
    """A committed results file must regenerate identical intervals."""
    values = [0.9, 0.8, 1.0, 0.6, 0.95, 0.7, 0.85]
    a, b = bootstrap_ci(values), bootstrap_ci(values)
    assert (a.point, a.low, a.high) == (b.point, b.low, b.high)


def test_bootstrap_point_is_the_mean():
    ci = bootstrap_ci([0.0, 1.0, 0.5])
    assert ci.point == pytest.approx(0.5)


def test_bootstrap_brackets_the_point_estimate():
    ci = bootstrap_ci([0.9, 0.8, 1.0, 0.6, 0.95])
    assert ci.low <= ci.point <= ci.high


def test_small_sample_yields_a_wide_interval():
    """The whole reason CIs are here: n=3 cannot support a tight claim."""
    wide = bootstrap_ci([0.0, 0.5, 1.0])
    narrow = bootstrap_ci([0.75, 0.76, 0.74, 0.75, 0.76, 0.75] * 10)
    assert (wide.high - wide.low) > (narrow.high - narrow.low)


def test_identical_values_give_a_degenerate_interval():
    ci = bootstrap_ci([0.8] * 10)
    assert ci.low == pytest.approx(0.8) and ci.high == pytest.approx(0.8)


def test_single_value_does_not_crash():
    ci = bootstrap_ci([0.7])
    assert (ci.point, ci.low, ci.high) == (0.7, 0.7, 0.7)


def test_empty_values_do_not_crash():
    assert bootstrap_ci([]).point == 0.0


def test_interval_is_stable_across_seed_choice():
    """Determinism is required; seed *sensitivity* is not.

    At a usable sample size the interval should barely move with the seed -- if it
    did, the seed would be doing the work instead of the data, and the published
    number would be an artifact of an arbitrary constant.
    """
    values = [0.9, 0.8, 1.0, 0.6, 0.95, 0.7, 0.85, 0.75, 0.65, 0.88] * 3
    a = bootstrap_ci(values, seed=BOOTSTRAP_SEED)
    b = bootstrap_ci(values, seed=BOOTSTRAP_SEED + 1)
    assert a.low == pytest.approx(b.low, abs=0.02)
    assert a.high == pytest.approx(b.high, abs=0.02)


def test_interval_formats_readably():
    assert str(bootstrap_ci([0.5] * 5)) == "0.50 [0.50-0.50]"


# --------------------------- bucket breakout ---------------------------

def test_aggregate_can_hide_a_failing_bucket():
    """The motivating case: a healthy aggregate concealing an adversarial collapse."""
    outcomes = [outcome(f"c{i}", "clean", 1.0) for i in range(9)]
    outcomes += [outcome("a1", "adversarial", 0.0)]

    report = build_report("baseline", outcomes)
    assert report.aggregate.f1.point == pytest.approx(0.9)
    assert report.by_bucket["adversarial"].f1.point == 0.0
    assert report.worst_bucket().bucket == "adversarial"


def test_every_bucket_present_gets_its_own_row():
    outcomes = [
        outcome("a", "clean"), outcome("b", "ambiguous"),
        outcome("c", "adversarial"), outcome("d", "empty"), outcome("e", "long"),
    ]
    report = build_report("x", outcomes)
    assert set(report.by_bucket) == {"clean", "ambiguous", "adversarial", "empty", "long"}
    assert all(b.n == 1 for b in report.by_bucket.values())


def test_worst_bucket_is_none_when_no_cases():
    assert build_report("x", []).worst_bucket() is None


# --------------------------- rates ---------------------------

def test_forbidden_rate_is_denominated_in_extractions():
    """One forbidden hit among 30 extractions is not the same as one among one."""
    many = build_report("x", [outcome(n_predicted=30, forbidden_hits=1)])
    few = build_report("x", [outcome(n_predicted=1, forbidden_hits=1)])
    assert many.aggregate.forbidden_rate == pytest.approx(1 / 30)
    assert few.aggregate.forbidden_rate == 1.0


def test_verbatim_and_near_verbatim_are_distinct_rates():
    report = build_report("x", [
        outcome(evidence_total=10, evidence_verbatim=8, evidence_near_verbatim=1)
    ])
    assert report.aggregate.verbatim_rate == pytest.approx(0.8)
    assert report.aggregate.near_verbatim_rate == pytest.approx(0.9)


def test_no_extractions_means_perfect_verbatim_not_zero():
    """An empty case cites no evidence; that is not an evidence failure."""
    report = build_report("x", [outcome(n_predicted=0, evidence_total=0,
                                        evidence_verbatim=0)])
    assert report.aggregate.verbatim_rate == 1.0
    assert report.aggregate.forbidden_rate == 0.0


def test_schema_validity_is_a_fraction_of_cases():
    report = build_report("x", [
        outcome("a", schema_valid=True), outcome("b", schema_valid=True),
        outcome("c", schema_valid=False), outcome("d", schema_valid=True),
    ])
    assert report.aggregate.schema_validity == pytest.approx(0.75)


def test_parse_methods_are_counted():
    """The fence fallback fired intermittently in the spike; track how often."""
    report = build_report("x", [
        outcome("a", parse_method="direct"), outcome("b", parse_method="direct"),
        outcome("c", parse_method="fence"),
    ])
    assert report.parse_methods == {"direct": 2, "fence": 1}


# --------------------------- cost and latency ---------------------------

def test_cost_sums_across_cases_and_buckets():
    report = build_report("x", [
        outcome("a", "clean", cost_usd=0.05), outcome("b", "empty", cost_usd=0.10)
    ])
    assert report.total_cost == pytest.approx(0.15)
    assert report.by_bucket["empty"].cost_usd == pytest.approx(0.10)


def test_latency_percentiles():
    outcomes = [outcome(f"c{i}", latency_s=float(i)) for i in range(1, 101)]
    report = build_report("x", outcomes)
    assert report.p50_latency == pytest.approx(50.5, abs=1.0)
    assert report.p95_latency == pytest.approx(95.0, abs=1.5)


def test_zero_latency_cached_results_are_excluded_from_percentiles():
    report = build_report("x", [outcome("a", latency_s=0.0), outcome("b", latency_s=10.0)])
    assert report.p50_latency == pytest.approx(10.0)


def test_percentile_of_empty_is_zero():
    assert percentile([], 50) == 0.0


# --------------------------- noise floor gate ---------------------------

def test_drop_within_noise_is_not_a_regression():
    """The spike's 0.40 floor: a 0.3 drop is indistinguishable from a re-run."""
    assert exceeds_noise_floor(0.90, 0.60, noise_floor=0.40) is False


def test_drop_clearing_twice_the_floor_is_a_regression():
    assert exceeds_noise_floor(0.95, 0.05, noise_floor=0.40) is True


def test_improvement_is_never_a_regression():
    assert exceeds_noise_floor(0.60, 0.90, noise_floor=0.10) is False


def test_multiple_is_configurable():
    assert exceeds_noise_floor(0.9, 0.5, noise_floor=0.15, multiple=1.0) is True
    assert exceeds_noise_floor(0.9, 0.5, noise_floor=0.15, multiple=3.0) is False
