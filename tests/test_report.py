"""US-009 -- report rendering and the two charts."""

from __future__ import annotations

from src.metrics import CaseOutcome, build_report
from src.report import (
    chart_cost_frontier,
    chart_f1_by_bucket,
    render_markdown,
    write_report,
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


def two_reports():
    strong = build_report("structured", [
        *[outcome(f"c{i}", "clean", 1.0) for i in range(4)],
        *[outcome(f"a{i}", "adversarial", 0.9) for i in range(4)],
    ])
    weak = build_report("cheaper", [
        *[outcome(f"c{i}", "clean", 0.95, cost_usd=0.01) for i in range(4)],
        *[outcome(f"a{i}", "adversarial", 0.2, cost_usd=0.01) for i in range(4)],
    ])
    return [strong, weak]


# --------------------------- markdown ---------------------------

def test_empty_reports_render_without_crashing():
    assert "No results" in render_markdown([])


def test_every_config_appears_in_the_aggregate_table():
    md = render_markdown(two_reports())
    assert "`structured`" in md and "`cheaper`" in md


def test_confidence_intervals_are_rendered_not_bare_points():
    md = render_markdown(two_reports())
    assert "[" in md and "-" in md
    assert "F1 (95% CI)" in md


def test_bucket_breakout_section_exists_for_every_bucket():
    md = render_markdown(two_reports())
    assert "## By bucket" in md
    assert "### `clean`" in md
    assert "### `adversarial`" in md


def test_a_hidden_failing_bucket_is_called_out_explicitly():
    """The whole point: an aggregate must not be readable without its worst bucket."""
    md = render_markdown(two_reports())
    assert "conceals" in md
    assert "`adversarial`" in md


def test_noise_floor_is_stated_when_known():
    md = render_markdown(two_reports(), noise_floor=0.40)
    assert "0.40" in md
    assert "indistinguishable from re-running" in md


def test_noise_floor_section_omitted_when_unknown():
    assert "noise floor" not in render_markdown(two_reports()).lower()


def test_dropped_coverage_is_logged_not_silent():
    md = render_markdown(two_reports(), dropped_coverage=["3 long cases not run"])
    assert "## Coverage dropped" in md
    assert "3 long cases not run" in md


def test_no_coverage_section_when_nothing_dropped():
    assert "Coverage dropped" not in render_markdown(two_reports())


def test_parse_method_counts_are_reported():
    reports = [build_report("x", [
        outcome("a", parse_method="direct"),
        outcome("b", parse_method="fence"),
    ])]
    md = render_markdown(reports)
    assert "## JSON recovery" in md
    assert "load-bearing" in md


def test_buckets_render_in_canonical_order():
    reports = [build_report("x", [
        outcome("a", "empty"), outcome("b", "clean"), outcome("c", "adversarial"),
    ])]
    md = render_markdown(reports)
    assert md.index("### `clean`") < md.index("### `adversarial`") < md.index("### `empty`")


def test_unknown_bucket_still_renders():
    reports = [build_report("x", [outcome("a", "surprise")])]
    assert "### `surprise`" in render_markdown(reports)


# --------------------------- charts ---------------------------

def test_f1_chart_is_written(tmp_path):
    path = chart_f1_by_bucket(two_reports(), tmp_path / "f1.png")
    assert path.exists() and path.stat().st_size > 1000


def test_cost_frontier_chart_is_written(tmp_path):
    path = chart_cost_frontier(two_reports(), tmp_path / "cost.png")
    assert path.exists() and path.stat().st_size > 1000


def test_write_report_produces_exactly_two_charts(tmp_path):
    out = write_report(two_reports(), tmp_path, noise_floor=0.4)
    assert out["markdown"].exists()
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 2, f"exactly two charts, got {[p.name for p in pngs]}"


def test_write_report_creates_missing_directory(tmp_path):
    out = write_report(two_reports(), tmp_path / "nested" / "deep")
    assert out["markdown"].exists()


def test_charts_handle_a_single_config(tmp_path):
    single = [build_report("only", [outcome("a", "clean")])]
    assert chart_f1_by_bucket(single, tmp_path / "a.png").exists()
    assert chart_cost_frontier(single, tmp_path / "b.png").exists()


def test_chart_handles_a_config_missing_a_bucket(tmp_path):
    """Configs need not cover identical buckets; the chart must not crash."""
    reports = [
        build_report("a", [outcome("x", "clean"), outcome("y", "empty")]),
        build_report("b", [outcome("x", "clean")]),
    ]
    assert chart_f1_by_bucket(reports, tmp_path / "f1.png").exists()
