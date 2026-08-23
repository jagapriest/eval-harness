"""Turn a raw model response plus a labeled case into a `CaseOutcome`.

This is the seam between the graders and the metrics layer. It exists as its own
module because three callers need it: the CLI, the noise measurement, and the
regression test -- and the regression test must reach it without importing anything
that touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graders.schema_grader import grade_schema
from .graders.set_grader import (
    evidence_is_verbatim,
    evidence_similarity,
    grade_set,
    load_aliases,
)
from .metrics import CaseOutcome

ROOT = Path(__file__).resolve().parent.parent
NEAR_VERBATIM = 0.95


def load_cases(split: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    """Load labeled cases, optionally filtered to a split.

    Falls back to all cases when `data/splits.json` does not exist yet -- it is
    written by US-001, and the harness must be runnable before then.
    """
    root = root or ROOT
    cases = []
    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        case["document"] = (root / case["source_path"]).read_text()
        cases.append(case)

    if not split:
        return cases

    splits_path = root / "data" / "splits.json"
    if not splits_path.exists():
        return cases

    wanted = set(json.loads(splits_path.read_text()).get(split, []))
    return [c for c in cases if c["case_id"] in wanted]


def grade_case(
    case: dict[str, Any],
    raw_text: str,
    aliases: dict[str, str] | None = None,
    cost_usd: float = 0.0,
    latency_s: float = 0.0,
) -> CaseOutcome:
    aliases = aliases if aliases is not None else load_aliases(ROOT / "data" / "aliases.json")
    document = case["document"]
    expected = case["expected"]

    schema = grade_schema(raw_text)
    competitors = schema.extraction.competitors if schema.extraction else []
    predicted = [c.name for c in competitors]

    set_result = grade_set(
        predicted,
        expected.get("competitors", []),
        expected.get("must_not_include", []),
        aliases,
    )

    verbatim = near = 0
    for comp in competitors:
        if evidence_is_verbatim(comp.evidence, document):
            verbatim += 1
        elif evidence_similarity(comp.evidence, document) >= NEAR_VERBATIM:
            near += 1

    return CaseOutcome(
        case_id=case["case_id"],
        bucket=case["bucket"],
        schema_valid=schema.valid,
        parse_method=schema.parse_method,
        precision=set_result.precision,
        recall=set_result.recall,
        f1=set_result.f1,
        n_predicted=len(predicted),
        n_expected=len(expected.get("competitors", [])),
        forbidden_hits=len(set_result.forbidden_hits),
        near_misses=len(set_result.near_misses),
        evidence_total=len(competitors),
        evidence_verbatim=verbatim,
        evidence_near_verbatim=near,
        cost_usd=cost_usd,
        latency_s=latency_s,
    )


def outcomes_to_jsonl(outcomes: list[CaseOutcome], path: Path) -> Path:
    """Write results as JSONL. The diff between runs is the regression signal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for outcome in sorted(outcomes, key=lambda o: o.case_id):
            fh.write(json.dumps(outcome.__dict__, sort_keys=True) + "\n")
    return path


def outcomes_from_jsonl(path: Path) -> list[CaseOutcome]:
    return [CaseOutcome(**json.loads(line)) for line in path.read_text().splitlines() if line]
