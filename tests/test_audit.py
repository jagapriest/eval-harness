"""Golden-set audit.

A wrong label looks exactly like a model error. These checks are the only thing
standing between a defective dataset and a confidently wrong result.
"""

from __future__ import annotations

import json

import pytest

from src.audit import (
    audit,
    fix,
    label_matches_document_form,
    name_in_document,
    render,
)

DOC = (
    "Our competitors include Dell Technologies Inc. and Lenovo Group Ltd., as well as "
    "public cloud providers such as AWS, GCP and Microsoft Azure. Deloitte is a partner."
)


def build(tmp_path, case_id="c1", bucket="clean", competitors=(), forbidden=(),
          disputed=(), document=DOC, **extra):
    (tmp_path / "data" / "cases").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "docs" / f"{case_id}.txt").write_text(document)
    (tmp_path / "data" / "aliases.json").write_text(json.dumps({
        "Amazon Web Services": ["AWS"],
        "Google": ["GCP", "Google Cloud Platform"],
        "Microsoft": ["Microsoft Azure", "Azure"],
        "Dell Technologies": ["Dell"],
    }))
    expected = {"competitors": list(competitors), "must_not_include": list(forbidden)}
    expected.update(extra)
    (tmp_path / "data" / "cases" / f"{case_id}.json").write_text(json.dumps({
        "case_id": case_id, "bucket": bucket,
        "source_path": f"data/docs/{case_id}.txt",
        "screening": {"company": "Acme", "proposed": [], "disputed": list(disputed)},
        "expected": expected,
    }))
    return tmp_path


def checks(report):
    return {f.check for f in report.findings}


# --------------------------- name matching ---------------------------

@pytest.mark.parametrize("name", [
    "Dell Technologies", "Dell Technologies Inc.", "Dell", "Lenovo Group Ltd.",
])
def test_findable_names(name):
    assert name_in_document(name, DOC)


def test_parenthetical_label_is_findable_via_either_arm():
    """'GCP (Google Cloud Platform)' -- the document writes only 'GCP'."""
    assert name_in_document("GCP (Google Cloud Platform)", DOC)


def test_absent_name_is_not_findable():
    assert not name_in_document("Weyland-Yutani", DOC)


def test_label_form_check_is_stricter_than_findability():
    """Findable in some form, but not in the document's own form."""
    assert name_in_document("GCP (Google Cloud Platform)", DOC)
    assert not label_matches_document_form("GCP (Google Cloud Platform)", DOC)
    assert label_matches_document_form("GCP", DOC)


# --------------------------- errors ---------------------------

def test_contradiction_is_an_error(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies"],
                         forbidden=["Dell"]))
    assert "contradiction" in checks(report)
    assert not report.ok


def test_alias_collision_within_a_list_is_an_error(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies"],
                         forbidden=["AWS", "Amazon Web Services"]))
    assert "alias-collision" in checks(report)
    assert not report.ok


def test_label_absent_from_document_is_an_error(tmp_path):
    report = audit(build(tmp_path, competitors=["Weyland-Yutani"]))
    assert "not-in-document" in checks(report)
    assert not report.ok


def test_clean_dataset_has_no_errors(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies"],
                         forbidden=["Deloitte"]))
    assert report.ok


# --------------------------- warnings ---------------------------

def test_undecided_disputed_item_warns(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies"],
                         disputed=["AWS (extracted as competitor, entities say partner)"]))
    assert "disputed-undecided" in checks(report)
    assert report.ok  # a warning, not a blocker


def test_decided_disputed_item_does_not_warn(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies", "AWS"],
                         disputed=["AWS (extracted as competitor, entities say partner)"]))
    assert "disputed-undecided" not in checks(report)


def test_disputed_resolved_into_must_not_include_does_not_warn(tmp_path):
    """Rejecting a disputed item is a decision too."""
    report = audit(build(tmp_path, competitors=["Dell Technologies"], forbidden=["AWS"],
                         disputed=["AWS (extracted as competitor, entities say partner)"]))
    assert "disputed-undecided" not in checks(report)


def test_deferred_item_warns(tmp_path):
    report = audit(build(tmp_path, competitors=["Dell Technologies"],
                         prelabel={"deferred": ["Lenovo Group Ltd."]}))
    assert "deferred" in checks(report)


def test_empty_bucket_with_competitors_warns(tmp_path):
    report = audit(build(tmp_path, bucket="empty", competitors=["Dell Technologies"]))
    assert "bucket-mismatch" in checks(report)


def test_clean_bucket_without_competitors_warns(tmp_path):
    report = audit(build(tmp_path, bucket="clean"))
    assert "bucket-mismatch" in checks(report)


def test_label_form_mismatch_warns_but_does_not_block(tmp_path):
    report = audit(build(tmp_path, competitors=["GCP (Google Cloud Platform)"]))
    assert "label-form" in checks(report)
    assert report.ok


# --------------------------- fix ---------------------------

def test_fix_collapses_alias_collisions_keeping_the_longer_form(tmp_path):
    root = build(tmp_path, competitors=["Dell Technologies"],
                 forbidden=["AWS", "Amazon Web Services"])
    assert not audit(root).ok

    changes = fix(root)
    assert any("AWS" in c for c in changes)

    case = json.loads((root / "data" / "cases" / "c1.json").read_text())
    assert case["expected"]["must_not_include"] == ["Amazon Web Services"]
    assert audit(root).ok


def test_fix_is_idempotent(tmp_path):
    root = build(tmp_path, forbidden=["AWS", "Amazon Web Services"],
                 competitors=["Dell Technologies"])
    fix(root)
    assert fix(root) == []


def test_fix_never_resolves_a_judgment_call(tmp_path):
    """Disputed and deferred items must survive --fix untouched."""
    root = build(tmp_path, competitors=["Dell Technologies"],
                 disputed=["AWS (extracted as competitor, entities say partner)"],
                 prelabel={"deferred": ["Lenovo Group Ltd."]})
    fix(root)
    report = audit(root)
    assert "disputed-undecided" in checks(report)
    assert "deferred" in checks(report)


def test_fix_leaves_a_clean_dataset_alone(tmp_path):
    root = build(tmp_path, competitors=["Dell Technologies"], forbidden=["Deloitte"])
    assert fix(root) == []


# --------------------------- reporting ---------------------------

def test_render_includes_counts_and_verdict(tmp_path):
    text = render(audit(build(tmp_path, competitors=["Dell Technologies"])))
    assert "GOLDEN SET AUDIT" in text
    assert "1 cases" in text


def test_render_states_blocking_errors(tmp_path):
    text = render(audit(build(tmp_path, competitors=["Weyland-Yutani"])))
    assert "must be fixed before scoring" in text


def test_real_dataset_has_no_blocking_errors():
    """Guards the committed golden set, not just the logic."""
    report = audit()
    assert report.ok, [f.detail for f in report.by_severity("ERROR")]
