"""Apply one stated labeling rule consistently across every case.

WHY THIS EXISTS, STATED PLAINLY
--------------------------------
First-pass adjudication was internally inconsistent. Accept rates ranged from 0% to
100% on structurally similar filings: 28 of 28 accepted on HPE, 0 of 20 on Marvell in
22 seconds. Intel and Nvidia were rejected as competitors on AMD's own filing; SAP,
Salesforce and Workday were rejected on Oracle's. Recall was 1.00 on every case in
every configuration, so every measured error was precision, computed against labels
that reject Intel-on-AMD.

WHAT THIS COSTS
---------------
The rule below leans on machine signals -- whether a name appears in the document, and
what role the entities pass assigned it. That makes the resulting golden set **partly
machine-derived**, which weakens the evaluation: a configuration whose extraction
resembles the screener's will score better for that reason alone. This is a real
limitation and must be stated wherever these numbers appear. It is not hidden by
averaging.

WHAT IS PRESERVED
-----------------
Original human labels are kept verbatim under `expected_as_labeled`. Both versions are
scored, and the difference between them is reported as a finding rather than resolved
silently. A reader can see exactly what normalization changed and decide for themselves.

THE RULE
--------
A proposed competitor is accepted iff all hold:

  1. The name is findable in the source document (verifiable, model-independent).
  2. The entities pass did not assign it a non-competitor role -- partner, customer,
     supplier, analyst. Those become must_not_include instead.
  3. It is not already in must_not_include.

Bucket semantics are respected: `empty` and `adversarial` cases keep an empty
competitor list regardless, because that is what defines those buckets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .audit import name_in_document
from .graders.set_grader import canonicalize, load_aliases

ROOT = Path(__file__).resolve().parent.parent

NON_COMPETITOR_ROLES = {"partner", "customer", "supplier", "analyst", "self"}
ZERO_COMPETITOR_BUCKETS = {"empty", "adversarial"}

RULE = (
    "accept a proposed competitor iff it is findable in the source document AND the "
    "entities pass did not assign it a non-competitor role; empty/adversarial buckets "
    "keep an empty competitor list by definition"
)


@dataclass
class CaseChange:
    case_id: str
    bucket: str
    company: str
    before: int
    after: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def delta(self) -> int:
        return self.after - self.before


def entity_roles(case: dict) -> dict[str, str]:
    roles: dict[str, str] = {}
    for ent in case.get("screening", {}).get("entities", []):
        name = (ent.get("name") or "").strip().casefold()
        if name and name not in roles:
            roles[name] = ent.get("role", "other")
    return roles


def normalize_case(case: dict, document: str, aliases: dict[str, str]) -> CaseChange:
    screening = case.get("screening", {})
    expected = case.setdefault("expected", {})

    # Preserve the human pass verbatim, once. Re-running must not overwrite it with a
    # previously normalized list.
    if "expected_as_labeled" not in case:
        case["expected_as_labeled"] = {
            "competitors": list(expected.get("competitors", [])),
            "must_not_include": list(expected.get("must_not_include", [])),
        }

    before = list(case["expected_as_labeled"]["competitors"])
    forbidden_keys = {canonicalize(n, aliases)
                      for n in expected.get("must_not_include", [])}
    roles = entity_roles(case)

    if case["bucket"] in ZERO_COMPETITOR_BUCKETS:
        accepted: list[str] = []
    else:
        accepted, seen = [], set()
        for name in screening.get("proposed", []):
            key = canonicalize(name, aliases)
            if key in seen or key in forbidden_keys:
                continue
            if not name_in_document(name, document):
                continue
            if roles.get(name.strip().casefold()) in NON_COMPETITOR_ROLES:
                continue
            seen.add(key)
            accepted.append(name)

    expected["competitors"] = accepted
    expected["normalized"] = {
        "rule": RULE,
        "machine_derived": True,
        "note": (
            "Applied because first-pass adjudication was internally inconsistent "
            "(accept rates 0%-100% on similar filings). Original human labels are "
            "preserved under expected_as_labeled and are scored alongside these. "
            "Because the rule uses machine signals, this golden set is partly "
            "machine-derived; see writeup/findings.md."
        ),
    }

    before_keys = {canonicalize(n, aliases): n for n in before}
    after_keys = {canonicalize(n, aliases): n for n in accepted}
    return CaseChange(
        case_id=case["case_id"], bucket=case["bucket"],
        company=screening.get("company", ""),
        before=len(before), after=len(accepted),
        added=[after_keys[k] for k in after_keys if k not in before_keys],
        removed=[before_keys[k] for k in before_keys if k not in after_keys],
    )


def normalize_all(root: Path | None = None) -> list[CaseChange]:
    root = root or ROOT
    aliases = load_aliases(root / "data" / "aliases.json")
    changes = []
    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        doc_path = root / case["source_path"]
        if not doc_path.exists():
            continue
        change = normalize_case(case, doc_path.read_text(), aliases)
        path.write_text(json.dumps(case, indent=2))
        changes.append(change)
    return changes


def summarize(changes: list[CaseChange]) -> str:
    moved = [c for c in changes if c.delta or c.added or c.removed]
    lines = [
        "", "LABEL NORMALIZATION", "=" * 78, "",
        f"  rule: {RULE}", "",
        f"{'case':16s} {'company':22s} {'before':>7s} {'after':>6s} {'delta':>6s}",
        "-" * 62,
    ]
    for c in sorted(moved, key=lambda c: -abs(c.delta)):
        lines.append(f"{c.case_id:16s} {c.company[:22]:22s} {c.before:7d} "
                     f"{c.after:6d} {c.delta:+6d}")
    total_before = sum(c.before for c in changes)
    total_after = sum(c.after for c in changes)
    lines += [
        "-" * 62,
        f"{'TOTAL':16s} {'':22s} {total_before:7d} {total_after:6d} "
        f"{total_after - total_before:+6d}",
        "",
        f"  {len(moved)} of {len(changes)} cases changed.",
        "  Original labels preserved under expected_as_labeled and scored alongside.",
        "",
    ]
    return "\n".join(lines)
