"""US-011 -- CLI and the grading seam.

Every test here runs offline. `run`, `noise`, and `prelabel` touch the network and are
exercised through their pure components instead.
"""

from __future__ import annotations

import json

import pytest

from src.cli import build_parser, main
from src.grade import grade_case, load_cases, outcomes_from_jsonl, outcomes_to_jsonl
from src.metrics import CaseOutcome, build_report

CASE = {
    "case_id": "t1",
    "bucket": "clean",
    "source_path": "x",
    "document": (
        "Our primary competitors are Dell Technologies Inc. and Lenovo Group Ltd. "
        "We partner with Deloitte."
    ),
    "expected": {
        "competitors": ["Dell Technologies", "Lenovo Group"],
        "must_not_include": ["Deloitte"],
    },
}

GOOD = json.dumps({
    "competitors": [
        {"name": "Dell Technologies Inc.",
         "evidence": "Our primary competitors are Dell Technologies Inc.",
         "confidence": "high"},
        {"name": "Lenovo Group Ltd.",
         "evidence": "Dell Technologies Inc. and Lenovo Group Ltd.",
         "confidence": "high"},
    ],
    "summary": "Competes with infrastructure vendors.",
})


# --------------------------- parser ---------------------------

@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--config", "baseline"],
        ["run", "--config", "baseline", "--split", "dev", "--no-cache"],
        ["grade", "--config", "baseline"],
        ["report", "--config", "a", "--config", "b"],
        ["noise", "--config", "baseline", "--replicates", "5"],
        ["prelabel", "--case", "clean_002"],
        ["prelabel", "--case", "clean_002", "--phase", "forbidden"],
        ["status"],
        ["status", "--todo"],
        ["audit"],
    ],
)
def test_every_documented_invocation_parses(argv):
    assert build_parser().parse_args(argv).command == argv[0]


def test_all_subcommands_are_registered():
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    registered = set(actions[0].choices)
    assert registered == {"run", "grade", "report", "noise", "prelabel", "status",
                          "audit"}


def test_report_config_flag_is_repeatable():
    args = build_parser().parse_args(["report", "--config", "a", "--config", "b"])
    assert args.config == ["a", "b"]


def test_split_rejects_an_unknown_value():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--config", "x", "--split", "prod"])


def test_missing_subcommand_exits():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


# --------------------------- grading seam ---------------------------

def test_grade_case_scores_a_correct_extraction():
    outcome = grade_case(CASE, GOOD)
    assert outcome.precision == 1.0 and outcome.recall == 1.0
    assert outcome.schema_valid is True
    assert outcome.evidence_verbatim == 2
    assert outcome.forbidden_hits == 0


def test_grade_case_flags_a_forbidden_hit():
    raw = json.dumps({
        "competitors": [{"name": "Deloitte", "evidence": "We partner with Deloitte.",
                         "confidence": "low"}],
        "summary": "s",
    })
    outcome = grade_case(CASE, raw)
    assert outcome.forbidden_hits == 1
    assert outcome.precision == 0.0


def test_grade_case_survives_unparseable_output():
    outcome = grade_case(CASE, "I cannot do that.")
    assert outcome.schema_valid is False
    assert outcome.parse_method == "failed"
    assert outcome.n_predicted == 0
    assert outcome.recall == 0.0


def test_grade_case_counts_a_fabricated_span_as_neither_verbatim_nor_near():
    raw = json.dumps({
        "competitors": [{"name": "Dell Technologies",
                         "evidence": "Acme leads the widget market entirely",
                         "confidence": "high"}],
        "summary": "s",
    })
    outcome = grade_case(CASE, raw)
    assert outcome.evidence_total == 1
    assert outcome.evidence_verbatim == 0
    assert outcome.evidence_near_verbatim == 0


def test_grade_case_carries_cost_and_latency_through():
    outcome = grade_case(CASE, GOOD, cost_usd=0.07, latency_s=9.5)
    assert outcome.cost_usd == 0.07 and outcome.latency_s == 9.5


# --------------------------- jsonl round trip ---------------------------

def test_results_round_trip_through_jsonl(tmp_path):
    outcomes = [grade_case(CASE, GOOD)]
    path = outcomes_to_jsonl(outcomes, tmp_path / "r.jsonl")
    restored = outcomes_from_jsonl(path)
    assert restored[0].__dict__ == outcomes[0].__dict__


def test_jsonl_is_sorted_so_run_diffs_are_readable(tmp_path):
    """The diff between runs is the regression signal; ordering must be stable."""
    outcomes = [
        CaseOutcome("z", "clean", True, "direct", 1, 1, 1, 1, 1, 0, 0, 1, 1, 0),
        CaseOutcome("a", "clean", True, "direct", 1, 1, 1, 1, 1, 0, 0, 1, 1, 0),
    ]
    path = outcomes_to_jsonl(outcomes, tmp_path / "r.jsonl")
    ids = [json.loads(line)["case_id"] for line in path.read_text().splitlines()]
    assert ids == ["a", "z"]


def test_jsonl_keys_are_sorted_so_diffs_are_line_stable(tmp_path):
    path = outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "r.jsonl")
    keys = list(json.loads(path.read_text().splitlines()[0]).keys())
    assert keys == sorted(keys)


# --------------------------- splits ---------------------------

def test_load_cases_falls_back_to_all_when_splits_file_absent(tmp_path):
    """The harness must be runnable before US-001 writes splits.json."""
    (tmp_path / "data" / "cases").mkdir(parents=True)
    (tmp_path / "data" / "docs").mkdir(parents=True)
    (tmp_path / "data" / "docs" / "d.txt").write_text("doc")
    (tmp_path / "data" / "cases" / "c1.json").write_text(json.dumps({
        "case_id": "c1", "bucket": "clean", "source_path": "data/docs/d.txt",
        "expected": {"competitors": []},
    }))
    assert len(load_cases("dev", root=tmp_path)) == 1


def test_load_cases_filters_when_splits_file_present(tmp_path):
    (tmp_path / "data" / "cases").mkdir(parents=True)
    (tmp_path / "data" / "docs").mkdir(parents=True)
    (tmp_path / "data" / "docs" / "d.txt").write_text("doc")
    for cid in ("c1", "c2"):
        (tmp_path / "data" / "cases" / f"{cid}.json").write_text(json.dumps({
            "case_id": cid, "bucket": "clean", "source_path": "data/docs/d.txt",
            "expected": {"competitors": []},
        }))
    (tmp_path / "data" / "splits.json").write_text(json.dumps({"dev": ["c1"], "test": ["c2"]}))

    assert [c["case_id"] for c in load_cases("dev", root=tmp_path)] == ["c1"]
    assert [c["case_id"] for c in load_cases("test", root=tmp_path)] == ["c2"]
    assert len(load_cases(None, root=tmp_path)) == 2


def test_real_cases_load_and_grade():
    """End to end against the committed spike cases -- no API involved."""
    cases = load_cases()
    assert len(cases) >= 5
    outcome = grade_case(cases[0], GOOD)
    assert outcome.bucket in {"clean", "ambiguous", "adversarial", "empty", "long"}


# --------------------------- grade / report commands ---------------------------

def test_grade_command_errors_clearly_without_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["grade", "--config", "ghost"])
    assert "no results" in str(exc.value).lower()


def test_report_command_errors_clearly_without_results(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    with pytest.raises(SystemExit):
        main(["report", "--config", "ghost"])


def test_grade_command_renders_from_a_results_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "baseline.jsonl")
    assert main(["grade", "--config", "baseline"]) == 0
    out = capsys.readouterr().out
    assert "# Results" in out and "By bucket" in out


def test_report_command_writes_markdown_and_two_charts(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "baseline.jsonl")
    assert main(["report", "--config", "baseline"]) == 0
    assert (tmp_path / "report" / "report.md").exists()
    assert len(list((tmp_path / "report").glob("*.png"))) == 2


def test_report_logs_a_missing_config_rather_than_dropping_it(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "baseline.jsonl")
    main(["report", "--config", "baseline", "--config", "ghost"])
    text = (tmp_path / "report" / "report.md").read_text()
    assert "Coverage dropped" in text and "ghost" in text


def test_report_picks_up_a_measured_noise_floor(tmp_path, monkeypatch):
    monkeypatch.setattr("src.cli._results_dir", lambda: tmp_path)
    outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "baseline.jsonl")
    (tmp_path / "noise_floor.json").write_text(json.dumps({"noise_floor": 0.4}))
    main(["report", "--config", "baseline"])
    assert "0.40" in (tmp_path / "report" / "report.md").read_text()


def test_build_report_is_reachable_from_restored_outcomes(tmp_path):
    path = outcomes_to_jsonl([grade_case(CASE, GOOD)], tmp_path / "r.jsonl")
    report = build_report("baseline", outcomes_from_jsonl(path))
    assert report.config_id == "baseline"
    assert report.aggregate.n == 1


# --------------------------- status ---------------------------

def test_case_progress_reports_phases_and_disputes(tmp_path):
    from src.cli import case_progress

    (tmp_path / "data" / "cases").mkdir(parents=True)
    # a: competitors adjudicated, must_not_include candidates still outstanding
    (tmp_path / "data" / "cases" / "a.json").write_text(json.dumps({
        "case_id": "a", "bucket": "clean",
        "screening": {"company": "Acme", "proposed": ["X", "Y"],
                      "proposed_must_not_include": ["P", "Q"], "disputed": ["Z (partner)"]},
        "expected": {"competitors": ["X"], "must_not_include": [], "prelabel": {}},
    }))
    # b: nothing proposed on either phase
    (tmp_path / "data" / "cases" / "b.json").write_text(json.dumps({
        "case_id": "b", "bucket": "empty",
        "screening": {"company": "Beta", "proposed": [], "proposed_must_not_include": [],
                      "disputed": []},
        "expected": {"competitors": [], "must_not_include": []},
    }))

    rows = {r["case_id"]: r for r in case_progress(root=tmp_path)}
    assert rows["a"]["done_competitors"] is True
    assert rows["a"]["done_forbidden"] is False    # 2 candidates, none adjudicated
    assert rows["a"]["disputed"] == 1

    # Zero candidates means there is nothing to adjudicate, so no provenance key is
    # written -- that must read as done, not as never-opened. 22 of 48 real cases are
    # in exactly this state on the competitor phase, and 4 on must_not_include.
    assert rows["b"]["done_competitors"] is True
    assert rows["b"]["done_forbidden"] is True


def test_zero_forbidden_candidates_counts_as_done(tmp_path):
    from src.cli import case_progress

    (tmp_path / "data" / "cases").mkdir(parents=True)
    (tmp_path / "data" / "cases" / "c.json").write_text(json.dumps({
        "case_id": "c", "bucket": "clean",
        "screening": {"company": "Gamma", "proposed": ["X"],
                      "proposed_must_not_include": [], "disputed": []},
        "expected": {"competitors": ["X"], "must_not_include": [], "prelabel": {}},
    }))
    row = case_progress(root=tmp_path)[0]
    assert row["done_competitors"] and row["done_forbidden"]


def test_case_progress_on_the_real_dataset():
    from src.cli import case_progress

    rows = case_progress()
    assert len(rows) == 48
    assert {r["bucket"] for r in rows} == {
        "clean", "ambiguous", "adversarial", "empty", "long"
    }
