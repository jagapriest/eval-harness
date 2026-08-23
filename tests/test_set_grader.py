"""US-004 -- set grader.

The set grader is the component most able to lie quietly: a normalization miss looks
exactly like a model error, and both show up as a precision drop. Every case below
came from something actually observed in a run.
"""

from __future__ import annotations

import json

import pytest

from src.graders.set_grader import (
    NEAR_MISS_RATIO,
    canonicalize,
    evidence_is_verbatim,
    evidence_similarity,
    grade_set,
    load_aliases,
    normalize_name,
    word_count,
)

ALIASES = load_aliases("data/aliases.json")
NEAR_VERBATIM = 0.95


# --------------------------- normalization ---------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Dell Technologies Inc.", "dell"),
        ("Dell", "dell"),
        ("Super Micro Computer, Inc.", "super micro computer"),
        ("Lenovo Group Ltd.", "lenovo"),
        ("Cisco Systems, Inc.", "cisco systems"),
        ("  NVIDIA   Corporation  ", "nvidia"),
    ],
)
def test_corporate_suffixes_are_stripped(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    "a,b",
    [
        # Observed in the 3-year HPE drift run: the same company rendered two ways
        # read as an add plus a drop, inflating churn.
        ("International Business Machines Corporation (IBM)", "International Business Machines"),
        ("Broadcom/VMware", "Broadcom"),
        ("Amazon Web Services (AWS)", "Amazon Web Services"),
        ("Microsoft Azure (Azure)", "Microsoft Azure"),
    ],
)
def test_parenthetical_and_slash_renderings_normalize_together(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_accents_are_folded():
    assert normalize_name("Atos SA") == normalize_name("Atós SA")


def test_normalize_is_idempotent():
    once = normalize_name("Dell Technologies Inc.")
    assert normalize_name(once) == once


def test_normalize_does_not_empty_a_suffix_only_name():
    """'Group' alone must not normalize to the empty string."""
    assert normalize_name("Group") == "group"


# --------------------------- aliases ---------------------------

@pytest.mark.parametrize(
    "a,b",
    [
        ("HPE", "Hewlett Packard Enterprise"),
        ("AWS", "Amazon Web Services"),
        ("GCP", "Google Cloud Platform"),
        ("Azure", "Microsoft Azure"),
        ("IBM", "International Business Machines"),
    ],
)
def test_alias_map_unifies_known_pairs(a, b):
    assert canonicalize(a, ALIASES) == canonicalize(b, ALIASES)


def test_unknown_name_passes_through_normalized():
    assert canonicalize("Weyland-Yutani Corp.", ALIASES) == "weyland yutani"


def test_alias_file_is_valid_and_non_empty():
    raw = json.loads(open("data/aliases.json").read())
    assert raw and all(isinstance(v, list) for v in raw.values())


# --------------------------- set membership ---------------------------

def test_true_positive_via_alias():
    r = grade_set(["HPE"], ["Hewlett Packard Enterprise"], aliases=ALIASES)
    assert r.true_positives == ["HPE"]
    assert r.precision == 1.0 and r.recall == 1.0


def test_near_miss_is_a_third_outcome_not_a_false_positive():
    r = grade_set(["Arista Network"], ["Arista Networks"], aliases=ALIASES)
    assert r.false_positives == []
    assert len(r.near_misses) == 1
    predicted, matched, ratio = r.near_misses[0]
    assert (predicted, matched) == ("Arista Network", "Arista Networks")
    assert ratio >= NEAR_MISS_RATIO


def test_genuinely_different_name_is_a_false_positive_not_a_near_miss():
    r = grade_set(["Databricks"], ["Snowflake"], aliases=ALIASES)
    assert r.false_positives == ["Databricks"]
    assert r.near_misses == []


def test_forbidden_hits_tracked_separately_from_false_positives():
    """must_not_include is the headline precision metric; it must not be buried."""
    r = grade_set(
        ["Databricks", "Acme"], ["Snowflake"],
        must_not_include=["Databricks"], aliases=ALIASES,
    )
    assert r.forbidden_hits == ["Databricks"]
    assert set(r.false_positives) == {"Databricks", "Acme"}


def test_empty_prediction_on_empty_expectation_is_perfect():
    """The empty bucket is where the spike found maximum variance -- pin the semantics."""
    r = grade_set([], [], aliases=ALIASES)
    assert r.precision == 1.0 and r.recall == 1.0 and r.f1 == 1.0


def test_any_extraction_on_an_empty_expectation_is_zero_precision():
    r = grade_set(["Databricks"], [], aliases=ALIASES)
    assert r.precision == 0.0
    assert r.f1 == 0.0


def test_missed_names_are_false_negatives():
    r = grade_set(["Dell"], ["Dell Technologies", "Lenovo Group"], aliases=ALIASES)
    assert r.true_positives == ["Dell"]
    assert r.false_negatives == ["Lenovo Group"]
    assert r.recall == 0.5


def test_f1_is_the_harmonic_mean():
    r = grade_set(["A", "B"], ["A", "C"], aliases={})
    assert r.precision == 0.5 and r.recall == 0.5
    assert r.f1 == pytest.approx(0.5)


def test_duplicate_predictions_collapse():
    """Two renderings of one company must not count as two extractions."""
    r = grade_set(["Dell", "Dell Technologies Inc."], ["Dell Technologies"], aliases=ALIASES)
    assert len(r.true_positives) == 1
    assert r.precision == 1.0


# --------------------------- evidence ---------------------------

DOC = (
    'Our primary IT Asset Disposition ("ITAD") competitors are ERI, Ingram Micro, '
    "Sage Sustainable Electronics, and Sims Recycling Solutions. We believe our "
    "competitive advantage over banks holds."
)


def test_exact_span_is_verbatim():
    assert evidence_is_verbatim("competitors are ERI, Ingram Micro", DOC)


def test_whitespace_and_case_are_normalized():
    assert evidence_is_verbatim("COMPETITORS   ARE   eri,  ingram micro", DOC)


def test_smart_quotes_normalize_to_straight():
    assert evidence_is_verbatim('IT Asset Disposition ("ITAD") competitors', DOC)


def test_mid_phrase_quote_is_not_verbatim_but_is_near():
    """Observed in the spike: the model started a quote mid-phrase to fit 25 words.

    Faithful, but not a contiguous substring. Exact and near must stay distinct
    outcomes -- collapsing them either manufactures failures or hides real ones.
    """
    span = "ITAD competitors are ERI, Ingram Micro, Sage Sustainable Electronics"
    assert evidence_is_verbatim(span, DOC) is False
    assert evidence_similarity(span, DOC) >= NEAR_VERBATIM


def test_fabricated_span_scores_far_below_near_verbatim():
    span = "Acme Corp is the market leader in enterprise widgets"
    assert evidence_is_verbatim(span, DOC) is False
    assert evidence_similarity(span, DOC) < NEAR_VERBATIM


def test_empty_span_is_not_verbatim():
    assert evidence_is_verbatim("", DOC) is False
    assert evidence_is_verbatim("   ", DOC) is False


def test_pagination_artifact_does_not_break_a_faithful_quote():
    """EDGAR injects '10 Table of Contents' mid-sentence.

    In the spike this manufactured a false verbatim failure and cost 14 points of
    measured accuracy with no change to the model. Documents are cleaned at fetch
    time; this pins the behavior the cleaner has to deliver.
    """
    import re

    dirty = (
        "Our primary IT Asset Disposition 10 Table of Contents competitors are ERI, "
        "Ingram Micro."
    )
    cleaned = re.sub(
        r"\s*\b\d{1,3}\s+Table of Contents?\b\s*", " ", dirty, flags=re.IGNORECASE
    )
    span = "Our primary IT Asset Disposition competitors are ERI, Ingram Micro."
    assert evidence_is_verbatim(span, dirty) is False
    assert evidence_is_verbatim(span, cleaned) is True


def test_word_count_enforces_the_span_cap():
    assert word_count("one two three") == 3
    assert word_count("  spaced   out  ") == 2
