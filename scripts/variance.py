"""Measure run-to-run variance of a single config on a fixed dataset.

There is no seed parameter in the Messages API -- output is non-deterministic by
construction. A regression is only a regression if it exceeds this noise floor, so
the floor has to be measured before any config comparison means anything.

Usage: python scripts/variance.py [--replicates 3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from src.graders.schema_grader import grade_schema  # noqa: E402
from src.graders.set_grader import grade_set, load_aliases  # noqa: E402
from src.runner import RunConfig, run_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicates", type=int, default=3)
    args = ap.parse_args()

    cfg = RunConfig(
        id="baseline",
        model="claude-opus-5",
        prompt_template=(ROOT / "prompts" / "baseline.md").read_text(),
        effort="medium",
        structured_output=False,
    )
    aliases = load_aliases(ROOT / "data" / "aliases.json")
    cases = []
    for path in sorted((ROOT / "data" / "cases").glob("*.json")):
        c = json.loads(path.read_text())
        c["document"] = (ROOT / c["source_path"]).read_text()
        cases.append(c)

    per_case: dict[str, list[float]] = {c["case_id"]: [] for c in cases}
    per_case_n: dict[str, list[int]] = {c["case_id"]: [] for c in cases}
    macro_f1: list[float] = []
    cost = 0.0

    for rep in range(1, args.replicates + 1):
        results = asyncio.run(
            run_all(
                [(c["case_id"], c["document"]) for c in cases],
                cfg, concurrency=5, use_cache=False,
            )
        )
        by_id = {r.case_id: r for r in results}
        f1s = []
        for case in cases:
            res = by_id[case["case_id"]]
            cost += res.cost(cfg)
            sg = grade_schema(res.raw_text)
            pred = [c.name for c in sg.extraction.competitors] if sg.extraction else []
            exp = case["expected"]
            sr = grade_set(pred, exp["competitors"], exp["must_not_include"], aliases)
            per_case[case["case_id"]].append(sr.f1)
            per_case_n[case["case_id"]].append(len(pred))
            f1s.append(sr.f1)
        macro_f1.append(statistics.mean(f1s))
        print(f"  replicate {rep}: macro-F1 = {statistics.mean(f1s):.3f}")

    print(f"\n{'case':18s} {'F1 per replicate':28s} {'spread':>8s}   n_extracted")
    print("-" * 78)
    for cid in per_case:
        vals = per_case[cid]
        spread = max(vals) - min(vals)
        print(f"{cid:18s} {str([round(v, 2) for v in vals]):28s} "
              f"{spread:8.2f}   {per_case_n[cid]}")

    print(f"\nmacro-F1 across replicates: {[round(v, 3) for v in macro_f1]}")
    print(f"  mean   = {statistics.mean(macro_f1):.3f}")
    if len(macro_f1) > 1:
        print(f"  stdev  = {statistics.stdev(macro_f1):.3f}")
    print(f"  spread = {max(macro_f1) - min(macro_f1):.3f}   <-- NOISE FLOOR")
    print(f"\n  A config delta must exceed this to count as a regression.")
    print(f"  cost of this variance probe: ${cost:.4f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
