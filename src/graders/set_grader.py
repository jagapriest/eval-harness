"""Deterministic grading of the extracted competitor set and evidence spans.

Two independent things are graded here, and keeping them separate matters:

1. **Set membership** -- precision / recall / F1 against the labeled expectation,
   plus a separately tracked false-positive rate on `must_not_include`.
2. **Evidence verbatim-ness** -- whether the cited span actually appears in the
   source document. This is a *deterministic* property and does not belong to the
   LLM judge; only evidence *quality* (does the span support the claim) is
   judgment. The original spec bundled both into the judge.

`near_miss` is a third outcome alongside match/miss: an extraction that is close
to an expected name but not equal under normalization. Counting those silently as
false positives is how set graders quietly lie about precision.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

NEAR_MISS_RATIO = 0.85

_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co", "limited",
    "ltd", "llc", "lp", "plc", "gmbh", "ag", "sa", "nv", "holdings", "group",
    "technologies", "technology",
)


def normalize_name(raw: str) -> str:
    """Casefold, strip punctuation/accents, and drop trailing corporate suffixes."""
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Strip suffixes repeatedly: "Dell Technologies Inc." -> "dell"
    changed = True
    while changed and text:
        changed = False
        for suffix in _SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
    return text


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load alias map and return normalized-alias -> normalized-canonical."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    out: dict[str, str] = {}
    for canonical, aliases in raw.items():
        canon_n = normalize_name(canonical)
        out[canon_n] = canon_n
        for alias in aliases:
            out[normalize_name(alias)] = canon_n
    return out


def canonicalize(raw: str, aliases: dict[str, str]) -> str:
    n = normalize_name(raw)
    return aliases.get(n, n)


def _norm_ws(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "--").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def evidence_is_verbatim(evidence: str, document: str) -> bool:
    """True if the evidence span appears in the document (whitespace/case-insensitive)."""
    if not evidence.strip():
        return False
    return _norm_ws(evidence) in _norm_ws(document)


def evidence_similarity(evidence: str, document: str) -> float:
    """Best partial-match ratio of the span against any same-length document window.

    Distinguishes a near-verbatim paraphrase (high ratio) from a fabricated span
    (low ratio) -- the difference between a model that quotes loosely and one that
    invents support.
    """
    ev, doc = _norm_ws(evidence), _norm_ws(document)
    if not ev or not doc:
        return 0.0
    if ev in doc:
        return 1.0
    window = len(ev)
    best = 0.0
    step = max(1, window // 4)
    for start in range(0, max(1, len(doc) - window), step):
        ratio = SequenceMatcher(None, ev, doc[start : start + window]).ratio()
        if ratio > best:
            best = ratio
        if best > 0.99:
            break
    return best


def word_count(text: str) -> int:
    return len(text.split())


@dataclass
class SetResult:
    true_positives: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    near_misses: list[tuple[str, str, float]] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = len(self.true_positives) + len(self.false_positives)
        return len(self.true_positives) / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = len(self.true_positives) + len(self.false_negatives)
        return len(self.true_positives) / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def grade_set(
    predicted: list[str],
    expected: list[str],
    must_not_include: list[str] | None = None,
    aliases: dict[str, str] | None = None,
) -> SetResult:
    aliases = aliases or {}
    must_not_include = must_not_include or []

    pred = {canonicalize(p, aliases): p for p in predicted}
    exp = {canonicalize(e, aliases): e for e in expected}
    forbidden = {canonicalize(f, aliases): f for f in must_not_include}

    result = SetResult()
    unmatched_expected = dict(exp)

    for pred_key, pred_raw in pred.items():
        if pred_key in exp:
            result.true_positives.append(pred_raw)
            unmatched_expected.pop(pred_key, None)
            continue
        if pred_key in forbidden:
            result.forbidden_hits.append(pred_raw)
        # Near-miss check before calling it a false positive.
        best_key, best_ratio = None, 0.0
        for exp_key in unmatched_expected:
            ratio = SequenceMatcher(None, pred_key, exp_key).ratio()
            if ratio > best_ratio:
                best_key, best_ratio = exp_key, ratio
        if best_key and best_ratio >= NEAR_MISS_RATIO:
            result.near_misses.append((pred_raw, unmatched_expected[best_key], best_ratio))
        else:
            result.false_positives.append(pred_raw)

    result.false_negatives = list(unmatched_expected.values())
    return result
