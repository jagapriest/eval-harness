"""US-002 -- model-assisted pre-labeling.

No live API calls: extraction output is supplied as a fixture string.
"""

from __future__ import annotations

import json

import pytest

from src.prelabel import (
    Adjudication,
    Candidate,
    adjudicate,
    apply_adjudication,
    candidates_from_output,
    format_candidate,
    record_cost,
)

DOCUMENT = (
    "Our primary competitors in data center infrastructure are technology vendors, "
    "such as Dell Technologies Inc., Super Micro Computer, Inc., and Lenovo Group Ltd. "
    "We also partner with Deloitte on implementation services."
)

RAW_OUTPUT = json.dumps(
    {
        "competitors": [
            {
                "name": "Dell Technologies",
                "evidence": "such as Dell Technologies Inc., Super Micro Computer, Inc.",
                "confidence": "high",
            },
            {
                "name": "Deloitte",
                "evidence": "We also partner with Deloitte on implementation services",
                "confidence": "low",
            },
            {
                "name": "Acme Corp",
                "evidence": "Acme Corp is a leading vendor in this space",
                "confidence": "medium",
            },
        ],
        "summary": "Competitive landscape summary.",
    }
)


def test_candidates_annotated_with_evidence_support():
    cands = candidates_from_output(RAW_OUTPUT, DOCUMENT)
    assert [c.name for c in cands] == ["Dell Technologies", "Deloitte", "Acme Corp"]

    by_name = {c.name: c for c in cands}
    assert by_name["Dell Technologies"].verbatim is True
    assert by_name["Deloitte"].verbatim is True

    # Fabricated span: not in the document, and similarity must be well below near-verbatim.
    acme = by_name["Acme Corp"]
    assert acme.verbatim is False
    assert acme.similarity < 0.95
    assert "UNSUPPORTED" in acme.evidence_flag


def test_candidates_from_unparseable_output_is_empty():
    assert candidates_from_output("not json at all", DOCUMENT) == []


def test_adjudicate_routes_each_answer():
    cands = [
        Candidate("A", "e", "high"),
        Candidate("B", "e", "high"),
        Candidate("C", "e", "high"),
    ]
    answers = iter(["y", "n", "?"])
    ticks = iter([100.0, 112.5])

    adj = adjudicate(cands, lambda _c: next(answers), clock=lambda: next(ticks))
    assert adj.accepted == ["A"]
    assert adj.rejected == ["B"]
    assert adj.deferred == ["C"]
    assert adj.seconds == 12.5
    assert adj.decided == 2


def test_unrecognized_input_defers_rather_than_accepts():
    """A mis-keyed label is worse than an unresolved one."""
    cands = [Candidate("A", "e", "high"), Candidate("B", "e", "high")]
    answers = iter(["", "banana"])
    adj = adjudicate(cands, lambda _c: next(answers))
    assert adj.accepted == []
    assert adj.deferred == ["A", "B"]


@pytest.mark.parametrize("answer", ["Y", " yes ", "YES"])
def test_accept_is_case_and_whitespace_insensitive(answer):
    adj = adjudicate([Candidate("A", "e", "high")], lambda _c: answer)
    assert adj.accepted == ["A"]


def test_apply_adjudication_unions_and_records_provenance(tmp_path):
    case_path = tmp_path / "clean_x.json"
    case_path.write_text(
        json.dumps(
            {
                "case_id": "clean_x",
                "bucket": "clean",
                "source_path": "data/docs/clean_x.txt",
                "expected": {
                    "competitors": ["Existing Hand Label"],
                    "must_not_include": [],
                    "notes": "",
                },
            }
        )
    )
    adj = Adjudication(accepted=["Dell Technologies"], rejected=["Deloitte"], seconds=9.0)
    out = apply_adjudication(case_path, adj, "prelabel", "claude-opus-5")

    # Union, never replace -- pre-existing hand labels must survive.
    assert out["expected"]["competitors"] == ["Existing Hand Label", "Dell Technologies"]

    prov = out["expected"]["prelabel"]
    assert prov["assisted"] is True
    assert prov["model"] == "claude-opus-5"
    assert prov["accepted"] == ["Dell Technologies"]
    assert prov["rejected"] == ["Deloitte"]

    # Persisted, not just returned.
    assert json.loads(case_path.read_text())["expected"]["prelabel"]["assisted"] is True


def test_apply_adjudication_does_not_duplicate_existing_name(tmp_path):
    case_path = tmp_path / "c.json"
    case_path.write_text(
        json.dumps({"case_id": "c", "bucket": "clean", "source_path": "x",
                    "expected": {"competitors": ["Dell Technologies"]}})
    )
    adj = Adjudication(accepted=["Dell Technologies"])
    out = apply_adjudication(case_path, adj, "prelabel", "m")
    assert out["expected"]["competitors"] == ["Dell Technologies"]


def test_record_cost_appends_jsonl(tmp_path):
    log = tmp_path / "results" / "labeling_cost.jsonl"
    record_cost(log, "c1", Adjudication(accepted=["A"], rejected=["B"], seconds=10.0))
    record_cost(log, "c2", Adjudication(accepted=["C"], deferred=["D"], seconds=6.0))

    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["case_id"] == "c1"
    assert lines[0]["seconds_per_candidate"] == 5.0
    assert lines[1]["deferred"] == 1


def test_record_cost_handles_zero_candidates(tmp_path):
    log = tmp_path / "labeling_cost.jsonl"
    record_cost(log, "empty", Adjudication(seconds=1.0))
    assert json.loads(log.read_text())["seconds_per_candidate"] == 0.0


def test_format_candidate_surfaces_support_flag():
    text = format_candidate(Candidate("A", "some span", "high", verbatim=True), 1, 3)
    assert "[1/3] A" in text
    assert "verbatim" in text
    assert "y/n/?" in text


def test_format_candidate_omits_evidence_when_absent():
    """Screener-sourced candidates carry no span; the prompt must not show empty rows."""
    text = format_candidate(Candidate("A", "", ""), 2, 5)
    assert "[2/5] A" in text
    assert "evidence" not in text
    assert "confidence" not in text


def test_accept_rest_applies_to_every_remaining_candidate():
    """A filing naming 60 customer logos would otherwise invite rubber-stamping."""
    cands = [Candidate(str(i), "", "") for i in range(5)]
    answers = iter(["n", "a"])
    adj = adjudicate(cands, lambda _c: next(answers))
    assert adj.rejected == ["0"]
    assert adj.accepted == ["1", "2", "3", "4"]
    assert adj.stopped_early is False


def test_quit_saves_progress_and_leaves_the_rest_unlabeled():
    cands = [Candidate(str(i), "", "") for i in range(5)]
    answers = iter(["y", "n", "q"])
    adj = adjudicate(cands, lambda _c: next(answers))
    assert adj.accepted == ["0"] and adj.rejected == ["1"]
    assert adj.deferred == []          # not silently defaulted
    assert adj.stopped_early is True


def test_forbidden_prompt_asks_the_consequence_not_the_field_name():
    from src.prelabel import format_forbidden

    text = format_forbidden("Deloitte", 3, 9)
    assert "[3/9] Deloitte" in text
    assert "precision failure" in text
    assert "must_not_include" not in text


def test_apply_forbidden_unions_and_records_provenance(tmp_path):
    from src.prelabel import apply_forbidden

    case_path = tmp_path / "c.json"
    case_path.write_text(json.dumps({
        "case_id": "c", "bucket": "adversarial", "source_path": "x",
        "expected": {"competitors": [], "must_not_include": ["Existing"]},
    }))
    out = apply_forbidden(case_path, Adjudication(accepted=["Deloitte"], rejected=["ISO"]))
    assert out["expected"]["must_not_include"] == ["Existing", "Deloitte"]
    assert out["expected"]["prelabel_forbidden"]["rejected"] == ["ISO"]
