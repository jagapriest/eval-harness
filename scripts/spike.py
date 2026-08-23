"""Vertical-slice spike: 5 cases end to end through the full pipeline.

Answers three questions before any dataset work happens:
  1. Is `evidence` verbatim-checkable, or do models paraphrase?
  2. What does a case actually cost and how long does it take?
  3. Does the output schema survive contact with real documents?

Usage: python scripts/spike.py [--no-cache] [--config baseline]
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

# Load ANTHROPIC_API_KEY from a local .env if it is not already in the environment.
import os  # noqa: E402
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from src.graders.schema_grader import grade_schema  # noqa: E402
from src.graders.set_grader import (  # noqa: E402
    evidence_is_verbatim,
    evidence_similarity,
    grade_set,
    load_aliases,

)
from src.runner import RunConfig, run_all  # noqa: E402

CONFIGS = {
    "baseline": RunConfig(
        id="baseline",
        model="claude-opus-5",
        prompt_template=(ROOT / "prompts" / "baseline.md").read_text(),
        effort="medium",
        structured_output=False,
        input_per_mtok=5.00,
        output_per_mtok=25.00,
    ),
}


def load_cases() -> list[dict]:
    cases = []
    for path in sorted((ROOT / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        case["document"] = (ROOT / case["source_path"]).read_text()
        cases.append(case)
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="baseline")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    cfg = CONFIGS[args.config]
    cases = load_cases()
    aliases = load_aliases(ROOT / "data" / "aliases.json")

    print(f"\nRunning config '{cfg.id}' ({cfg.model}, effort={cfg.effort}) "
          f"on {len(cases)} cases\n")

    results = asyncio.run(
        run_all(
            [(c["case_id"], c["document"]) for c in cases],
            cfg,
            concurrency=5,
            use_cache=not args.no_cache,
        )
    )
    by_id = {r.case_id: r for r in results}

    verbatim_flags: list[bool] = []
    similarities: list[float] = []
    non_verbatim_examples: list[tuple[str, str, float]] = []
    rows = []
    total_cost = 0.0

    for case in cases:
        res = by_id[case["case_id"]]
        if res.error:
            print(f"  !! {case['case_id']}: {res.error}")
            continue

        total_cost += res.cost(cfg)
        sg = grade_schema(res.raw_text)
        exp = case["expected"]

        predicted = [c.name for c in sg.extraction.competitors] if sg.extraction else []
        setres = grade_set(
            predicted, exp["competitors"], exp["must_not_include"], aliases
        )

        case_verbatim = 0
        if sg.extraction:
            for comp in sg.extraction.competitors:
                ok = evidence_is_verbatim(comp.evidence, case["document"])
                verbatim_flags.append(ok)
                if ok:
                    case_verbatim += 1
                    similarities.append(1.0)
                else:
                    sim = evidence_similarity(comp.evidence, case["document"])
                    similarities.append(sim)
                    if len(non_verbatim_examples) < 8:
                        non_verbatim_examples.append(
                            (case["case_id"], comp.evidence, sim)
                        )

        rows.append({
            "case_id": case["case_id"],
            "bucket": case["bucket"],
            "schema_ok": sg.valid,
            "parse": sg.parse_method,
            "n_pred": len(predicted),
            "n_exp": len(exp["competitors"]),
            "tp": len(setres.true_positives),
            "fp": len(setres.false_positives),
            "fn": len(setres.false_negatives),
            "near": len(setres.near_misses),
            "forbidden": len(setres.forbidden_hits),
            "precision": setres.precision,
            "recall": setres.recall,
            "f1": setres.f1,
            "verbatim": f"{case_verbatim}/{len(predicted)}" if predicted else "-",
            "over_len": len(sg.over_length_evidence),
            "cost": res.cost(cfg),
            "latency": res.latency_s,
            "cached": res.from_cache,
            "_setres": setres,
            "_sg": sg,
        })

    # ---------------- report ----------------
    print(f"{'case':18s} {'bucket':12s} {'sch':4s} {'parse':7s} "
          f"{'pred':>4s} {'exp':>4s} {'tp':>3s} {'fp':>3s} {'fn':>3s} {'nm':>3s} "
          f"{'!!':>3s} {'P':>5s} {'R':>5s} {'F1':>5s} {'verbatim':>9s} {'$':>8s} {'s':>6s}")
    print("-" * 132)
    for r in rows:
        print(f"{r['case_id']:18s} {r['bucket']:12s} "
              f"{'ok' if r['schema_ok'] else 'FAIL':4s} {r['parse']:7s} "
              f"{r['n_pred']:4d} {r['n_exp']:4d} {r['tp']:3d} {r['fp']:3d} "
              f"{r['fn']:3d} {r['near']:3d} {r['forbidden']:3d} "
              f"{r['precision']:5.2f} {r['recall']:5.2f} {r['f1']:5.2f} "
              f"{r['verbatim']:>9s} {r['cost']:8.4f} {r['latency']:6.1f}")

    print("\n" + "=" * 60)
    print("SPIKE QUESTIONS")
    print("=" * 60)

    n_ev = len(verbatim_flags)
    n_ok = sum(verbatim_flags)
    print(f"\n1. EVIDENCE VERBATIM-NESS  ({n_ev} spans across all cases)")
    if n_ev:
        print(f"   exact verbatim (normalized): {n_ok}/{n_ev} = {n_ok / n_ev:.1%}")
        near = [s for s in similarities if s < 1.0]
        if near:
            print(f"   non-verbatim similarity: median={statistics.median(near):.2f} "
                  f"min={min(near):.2f} max={max(near):.2f}")
        over = sum(r["over_len"] for r in rows)
        print(f"   spans over 25 words: {over}")
        if non_verbatim_examples:
            print("\n   non-verbatim examples:")
            for cid, ev, sim in non_verbatim_examples:
                snippet = ev if len(ev) <= 90 else ev[:87] + "..."
                print(f"     [{sim:.2f}] {cid}: {snippet}")

    print(f"\n2. COST & LATENCY")
    costs = [r["cost"] for r in rows]
    lats = [r["latency"] for r in rows if not r["cached"]]
    if costs:
        print(f"   cost/case: mean=${statistics.mean(costs):.4f} "
              f"total=${sum(costs):.4f}")
        print(f"   projected 50 cases x 3 configs: "
              f"${statistics.mean(costs) * 150:.2f}")
    if lats:
        print(f"   latency: median={statistics.median(lats):.1f}s max={max(lats):.1f}s")
    else:
        print("   latency: all cached")

    print(f"\n3. SCHEMA")
    print(f"   valid: {sum(r['schema_ok'] for r in rows)}/{len(rows)}")
    methods = {}
    for r in rows:
        methods[r["parse"]] = methods.get(r["parse"], 0) + 1
    print(f"   parse method: {methods}")

    print(f"\n4. HALLUCINATION (must_not_include hits)")
    for r in rows:
        if r["forbidden"]:
            names = ", ".join(r["_setres"].forbidden_hits)
            print(f"   {r['case_id']}: {names}")
    total_forbidden = sum(r["forbidden"] for r in rows)
    total_pred = sum(r["n_pred"] for r in rows)
    print(f"   total: {total_forbidden} hits / {total_pred} extractions "
          f"= {total_forbidden / total_pred:.1%}" if total_pred else "   no extractions")

    empty_rows = [r for r in rows if r["n_exp"] == 0]
    if empty_rows:
        fp_on_empty = sum(r["n_pred"] for r in empty_rows)
        print(f"\n   on {len(empty_rows)} empty cases the model named "
              f"{fp_on_empty} competitors (expected 0)")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
