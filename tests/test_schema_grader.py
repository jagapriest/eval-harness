"""US-005 -- schema grader.

The point of this grader is not only *whether* JSON was recovered but *how*. The
production bank-intelligence function does JSON.parse() with a regex fallback, and the
spike showed the fallback firing intermittently on the same prompt and model -- run 1
needed a markdown-fence strip on the largest case, run 2 did not. An undocumented,
intermittently load-bearing fallback is the worst kind, so parse_method is recorded on
every result.
"""

from __future__ import annotations

import json

import pytest

from src.graders.schema_grader import MAX_EVIDENCE_WORDS, grade_schema


def payload(**overrides):
    body = {
        "competitors": [
            {"name": "Dell Technologies", "evidence": "such as Dell Technologies Inc.",
             "confidence": "high"}
        ],
        "summary": "A short competitive summary.",
    }
    body.update(overrides)
    return body


# --------------------------- parse paths ---------------------------

def test_direct_json_parses():
    r = grade_schema(json.dumps(payload()))
    assert r.valid is True
    assert r.parse_method == "direct"
    assert r.extraction is not None


def test_leading_and_trailing_whitespace_still_direct():
    r = grade_schema("\n\n  " + json.dumps(payload()) + "  \n")
    assert r.parse_method == "direct"
    assert r.valid is True


def test_markdown_fence_is_recovered_and_reported():
    """Observed in the spike despite the prompt saying 'Return only JSON'."""
    r = grade_schema("```json\n" + json.dumps(payload()) + "\n```")
    assert r.valid is True
    assert r.parse_method == "fence"


def test_bare_fence_without_language_tag_is_recovered():
    r = grade_schema("```\n" + json.dumps(payload()) + "\n```")
    assert r.parse_method == "fence"


def test_prose_wrapped_json_falls_back_to_regex():
    r = grade_schema(
        "Here is the analysis you requested:\n"
        + json.dumps(payload())
        + "\nLet me know if you need more detail."
    )
    assert r.valid is True
    assert r.parse_method == "regex"


def test_unparseable_output_fails_cleanly():
    r = grade_schema("I was unable to complete this request.")
    assert r.valid is False
    assert r.parse_method == "failed"
    assert r.extraction is None
    assert r.errors


def test_empty_output_fails():
    r = grade_schema("")
    assert r.valid is False
    assert r.parse_method == "failed"


def test_truncated_json_fails_rather_than_partially_parsing():
    truncated = json.dumps(payload())[:-12]
    r = grade_schema(truncated)
    assert r.valid is False
    assert r.extraction is None


def test_parse_method_is_recorded_even_on_schema_failure():
    """A schema failure must not erase how the JSON was recovered."""
    bad = payload(competitors=[{"name": "X", "evidence": "e", "confidence": "certain"}])
    r = grade_schema("```json\n" + json.dumps(bad) + "\n```")
    assert r.valid is False
    assert r.parse_method == "fence"


# --------------------------- schema validation ---------------------------

def test_invalid_confidence_enum_is_rejected():
    bad = payload(competitors=[{"name": "X", "evidence": "e", "confidence": "certain"}])
    r = grade_schema(json.dumps(bad))
    assert r.valid is False
    assert "schema validation failed" in r.errors[0]


def test_missing_required_field_is_rejected():
    bad = payload(competitors=[{"name": "X", "confidence": "high"}])
    r = grade_schema(json.dumps(bad))
    assert r.valid is False


def test_missing_summary_is_rejected():
    body = payload()
    del body["summary"]
    assert grade_schema(json.dumps(body)).valid is False


def test_empty_competitor_list_is_valid():
    """The empty answer is correct on 3 of 5 spike documents. It must not fail."""
    r = grade_schema(json.dumps(payload(competitors=[])))
    assert r.valid is True
    assert r.extraction.competitors == []


def test_over_length_evidence_fails_and_is_reported():
    long_span = " ".join(f"word{i}" for i in range(MAX_EVIDENCE_WORDS + 5))
    bad = payload(
        competitors=[{"name": "X", "evidence": long_span, "confidence": "high"}]
    )
    r = grade_schema(json.dumps(bad))
    assert r.valid is False
    assert len(r.over_length_evidence) == 1
    assert str(MAX_EVIDENCE_WORDS) in r.errors[0]


def test_evidence_at_exactly_the_cap_passes():
    span = " ".join(f"word{i}" for i in range(MAX_EVIDENCE_WORDS))
    r = grade_schema(
        json.dumps(payload(competitors=[
            {"name": "X", "evidence": span, "confidence": "high"}
        ]))
    )
    assert r.valid is True
    assert r.over_length_evidence == []


def test_multiple_over_length_spans_are_all_counted():
    long_span = " ".join(f"w{i}" for i in range(MAX_EVIDENCE_WORDS + 1))
    bad = payload(competitors=[
        {"name": "A", "evidence": long_span, "confidence": "high"},
        {"name": "B", "evidence": long_span, "confidence": "low"},
        {"name": "C", "evidence": "short span", "confidence": "medium"},
    ])
    r = grade_schema(json.dumps(bad))
    assert len(r.over_length_evidence) == 2


@pytest.mark.parametrize("level", ["high", "medium", "low"])
def test_every_confidence_level_is_accepted(level):
    r = grade_schema(
        json.dumps(payload(competitors=[
            {"name": "X", "evidence": "e", "confidence": level}
        ]))
    )
    assert r.valid is True


def test_json_array_at_top_level_is_rejected():
    """The contract is an object; a bare array must not slip through."""
    assert grade_schema(json.dumps([{"name": "X"}])).valid is False


def test_over_length_defaults_to_empty_list_not_none():
    assert grade_schema("garbage").over_length_evidence == []
