"""Command-line entry point for the eval harness.

    python -m src.cli run      --config baseline [--split dev] [--no-cache]
    python -m src.cli grade    --config baseline [--split dev]
    python -m src.cli report   --config baseline --config structured
    python -m src.cli noise    --config baseline [--replicates 3]
    python -m src.cli prelabel --case clean_002
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """Load ANTHROPIC_API_KEY from a local .env if not already in the environment."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_case(case_id: str) -> tuple[Path, dict, str]:
    path = ROOT / "data" / "cases" / f"{case_id}.json"
    if not path.exists():
        raise SystemExit(f"no such case: {case_id} (looked in {path})")
    case = json.loads(path.read_text())
    document = (ROOT / case["source_path"]).read_text()
    return path, case, document


def _results_dir() -> Path:
    return ROOT / "results"


def _rel(path: Path) -> str:
    """Display path, relative to the repo when possible.

    relative_to() raises for anything outside ROOT, which happens whenever results
    are written elsewhere. Printing a path must never crash a completed run.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------- run ---------------------------

def cmd_run(args: argparse.Namespace) -> int:
    from .config import load_named
    from .grade import grade_case, load_cases, outcomes_to_jsonl
    from .graders.set_grader import load_aliases
    from .metrics import build_report
    from .runner import run_all

    load_env()
    cfg = load_named(args.config)
    cases = load_cases(args.split)
    if not cases:
        raise SystemExit(f"no cases found for split={args.split!r}")

    print(f"running '{cfg.id}' ({cfg.model}) on {len(cases)} cases"
          + (f" [split={args.split}]" if args.split else ""))

    responses = asyncio.run(
        run_all([(c["case_id"], c["document"]) for c in cases], cfg,
                concurrency=args.concurrency, use_cache=not args.no_cache)
    )
    by_id = {r.case_id: r for r in responses}

    failed = [r for r in responses if r.error]
    for r in failed:
        print(f"  !! {r.case_id}: {r.error}")

    aliases = load_aliases(ROOT / "data" / "aliases.json")
    outcomes = [
        grade_case(c, by_id[c["case_id"]].raw_text, aliases,
                   by_id[c["case_id"]].cost(cfg), by_id[c["case_id"]].latency_s)
        for c in cases if not by_id[c["case_id"]].error
    ]

    suffix = f"_{args.split}" if args.split else ""
    out = outcomes_to_jsonl(outcomes, _results_dir() / f"{cfg.id}{suffix}.jsonl")
    report = build_report(cfg.id, outcomes)

    cached = sum(1 for r in responses if r.from_cache)
    print(f"\n  F1 {report.aggregate.f1}   precision {report.aggregate.precision:.2f}"
          f"   recall {report.aggregate.recall:.2f}")
    worst = report.worst_bucket()
    if worst and worst.f1.point < report.aggregate.f1.point:
        print(f"  worst bucket: {worst.bucket} at {worst.f1.point:.2f} (n={worst.n})")
    print(f"  cost ${report.total_cost:.4f}   {cached}/{len(responses)} from cache")
    print(f"  written: {_rel(out)}\n")
    return 1 if failed else 0


# --------------------------- grade ---------------------------

def cmd_grade(args: argparse.Namespace) -> int:
    """Re-grade an existing results file without touching the API."""
    from .grade import outcomes_from_jsonl
    from .metrics import build_report
    from .report import render_markdown

    suffix = f"_{args.split}" if args.split else ""
    path = _results_dir() / f"{args.config}{suffix}.jsonl"
    if not path.exists():
        raise SystemExit(f"no results at {path}. Run first: python -m src.cli run "
                         f"--config {args.config}")
    report = build_report(args.config, outcomes_from_jsonl(path))
    print(render_markdown([report]))
    return 0


# --------------------------- report ---------------------------

def cmd_report(args: argparse.Namespace) -> int:
    from .grade import outcomes_from_jsonl
    from .metrics import build_report
    from .report import write_report

    suffix = f"_{args.split}" if args.split else ""
    reports, missing = [], []
    for name in args.config:
        path = _results_dir() / f"{name}{suffix}.jsonl"
        if not path.exists():
            missing.append(name)
            continue
        reports.append(build_report(name, outcomes_from_jsonl(path)))
    if not reports:
        raise SystemExit(f"no results found for: {', '.join(args.config)}")

    floor = None
    floor_path = _results_dir() / "noise_floor.json"
    if floor_path.exists():
        floor = json.loads(floor_path.read_text()).get("noise_floor")

    dropped = [f"config '{n}' has no results file and is absent from this report"
               for n in missing]
    out = write_report(reports, _results_dir() / "report", floor, dropped)
    for label, path in out.items():
        print(f"  {label:14s} {_rel(path)}")
    return 0


# --------------------------- noise ---------------------------

def cmd_noise(args: argparse.Namespace) -> int:
    from . import noise as noise_mod
    from .config import load_named

    load_env()
    cfg = load_named(args.config)
    print(f"measuring noise floor: '{cfg.id}' x{args.replicates}"
          + (f" on split '{args.split}'" if args.split else ""))
    result = noise_mod.measure(cfg, args.replicates, args.split, args.concurrency)
    print(noise_mod.summarize(result))
    path = noise_mod.write(result)
    print(f"  written: {_rel(path)}\n")
    return 0


# --------------------------- prelabel ---------------------------

def cmd_prelabel(args: argparse.Namespace) -> int:
    """Adjudicate a case: competitors first, then must_not_include.

    Uses the candidates the screener already produced. Only calls the API when a case
    has no stored proposals -- re-extracting would spend money redoing work, and would
    do it with a *different* config than the screener used.
    """
    from .prelabel import (
        Candidate,
        adjudicate,
        apply_adjudication,
        apply_forbidden,
        candidates_from_output,
        format_candidate,
        format_forbidden,
        record_cost,
    )

    path, case, document = load_case(args.case)
    screening = case.get("screening", {})
    already = set(case["expected"].get("competitors", []))

    print(f"\n{args.case} ({case['bucket']}) -- {screening.get('company', 'unknown')}")
    disputed = screening.get("disputed", [])
    if disputed:
        print(f"\n  DISPUTED -- the two screening passes disagree on these:")
        for item in disputed:
            print(f"    * {item}")
        print("  Decide these deliberately; they are the most informative in the set.")

    def ask(text: str) -> str:
        try:
            return input(text)
        except EOFError:
            return "q"

    # ---- phase 1: competitors ----
    if args.phase in ("competitors", "both"):
        proposed = screening.get("proposed")
        if proposed is None:
            from .runner import RunConfig, run_all

            load_env()
            cfg = RunConfig(
                id="prelabel", model=args.model,
                prompt_template=(ROOT / "prompts" / "structured.md").read_text(),
                effort="high", structured_output=True,
            )
            result = asyncio.run(run_all([(args.case, document)], cfg, concurrency=1))[0]
            if result.error:
                raise SystemExit(f"extraction failed: {result.error}")
            candidates = candidates_from_output(result.raw_text, document)
        else:
            candidates = [Candidate(name=n, evidence="", confidence="") for n in proposed]

        fresh = [c for c in candidates if c.name not in already]
        if not fresh:
            print("\n  competitors: nothing proposed. Expected stays empty "
                  "(correct for empty/adversarial cases).")
        else:
            print(f"\n  COMPETITORS -- {len(fresh)} to review")
            print("  Accept only entities NAMED in the document, competing in its "
                  "PRIMARY market (R-1).")
            counter = {"i": 0}

            def prompt(cand):
                counter["i"] += 1
                return ask(format_candidate(cand, counter["i"], len(fresh)))

            adj = adjudicate(fresh, prompt)
            apply_adjudication(path, adj, "screening", screening.get("model", "n/a"))
            record_cost(_results_dir() / "labeling_cost.jsonl", args.case, adj)
            print(f"\n  +{len(adj.accepted)} accepted, {len(adj.rejected)} rejected, "
                  f"{len(adj.deferred)} deferred"
                  + ("  [stopped early]" if adj.stopped_early else ""))

    # ---- phase 2: must_not_include ----
    if args.phase in ("forbidden", "both"):
        case = json.loads(path.read_text())
        have = set(case["expected"].get("must_not_include", []))
        names = [n for n in screening.get("proposed_must_not_include", []) if n not in have]
        if not names:
            print("\n  must_not_include: nothing proposed.")
        else:
            print(f"\n  MUST_NOT_INCLUDE -- {len(names)} to review")
            print("  Keep plausible rivals. Reject standards bodies, auditors, and "
                  "anything nobody would mistake for a competitor.")
            counter = {"i": 0}

            def prompt_f(cand):
                counter["i"] += 1
                return ask(format_forbidden(cand.name, counter["i"], len(names)))

            adj_f = adjudicate(
                [Candidate(name=n, evidence="", confidence="") for n in names], prompt_f
            )
            apply_forbidden(path, adj_f)
            print(f"\n  +{len(adj_f.accepted)} added to must_not_include, "
                  f"{len(adj_f.rejected)} rejected"
                  + ("  [stopped early]" if adj_f.stopped_early else ""))

    final = json.loads(path.read_text())
    print(f"\n  {args.case}: {len(final['expected']['competitors'])} competitors, "
          f"{len(final['expected']['must_not_include'])} must_not_include\n")
    return 0


# --------------------------- status ---------------------------

def case_progress(root: Path | None = None) -> list[dict]:
    """Per-case labeling progress. Pure, so it can be tested and reused."""
    root = root or ROOT
    rows = []
    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        expected = case.get("expected", {})
        screening = case.get("screening", {})
        n_comp = len(expected.get("competitors", []))
        n_forb = len(expected.get("must_not_include", []))
        did_comp = "prelabel" in expected
        did_forb = "prelabel_forbidden" in expected
        proposed = len(screening.get("proposed", []))
        # A case with no proposals is done on the competitor phase once it has been
        # looked at; correctly-empty is a real answer, not missing work.
        rows.append({
            "case_id": case["case_id"],
            "bucket": case["bucket"],
            "company": screening.get("company", ""),
            "competitors": n_comp,
            "must_not_include": n_forb,
            "proposed": proposed,
            "proposed_forbidden": len(screening.get("proposed_must_not_include", [])),
            "disputed": len(screening.get("disputed", [])),
            "done_competitors": did_comp or proposed == 0,
            "done_forbidden": did_forb,
        })
    return rows


def cmd_status(args: argparse.Namespace) -> int:
    rows = case_progress()
    if not rows:
        raise SystemExit("no cases in data/cases/")

    todo = [r for r in rows if not (r["done_competitors"] and r["done_forbidden"])]
    print(f"\n{'case':18s} {'bucket':12s} {'company':26s} {'comp':>5s} {'!inc':>5s} "
          f"{'disp':>5s}  status")
    print("-" * 88)
    for r in rows:
        if args.todo and r["done_competitors"] and r["done_forbidden"]:
            continue
        marks = ("C" if r["done_competitors"] else "-") + \
                ("F" if r["done_forbidden"] else "-")
        flag = "  <- disputed" if r["disputed"] else ""
        print(f"{r['case_id']:18s} {r['bucket']:12s} {r['company'][:26]:26s} "
              f"{r['competitors']:5d} {r['must_not_include']:5d} {r['disputed']:5d}"
              f"  [{marks}]{flag}")

    done = len(rows) - len(todo)
    disputed = sum(r["disputed"] for r in rows)
    print(f"\n  {done}/{len(rows)} cases complete  "
          f"(C = competitors adjudicated, F = must_not_include adjudicated)")
    if disputed:
        print(f"  {disputed} disputed items across "
              f"{sum(1 for r in rows if r['disputed'])} cases -- decide these first")
    if todo:
        print(f"\n  next: ./label {todo[0]['case_id']}\n")
    else:
        print("\n  dataset fully adjudicated.\n")
    return 0


# --------------------------- parser ---------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="LLM eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_split(p):
        p.add_argument("--split", choices=["dev", "test"], default=None,
                       help="restrict to a split (all cases if splits.json is absent)")

    run = sub.add_parser("run", help="run a config and grade the results")
    run.add_argument("--config", required=True)
    run.add_argument("--no-cache", action="store_true")
    run.add_argument("--concurrency", type=int, default=5)
    add_split(run)
    run.set_defaults(func=cmd_run)

    grade = sub.add_parser("grade", help="re-grade an existing results file, no API calls")
    grade.add_argument("--config", required=True)
    add_split(grade)
    grade.set_defaults(func=cmd_grade)

    report = sub.add_parser("report", help="write the markdown report and two charts")
    report.add_argument("--config", action="append", required=True,
                        help="repeatable; one per config to compare")
    add_split(report)
    report.set_defaults(func=cmd_report)

    noise = sub.add_parser("noise", help="measure the run-to-run noise floor")
    noise.add_argument("--config", required=True)
    noise.add_argument("--replicates", type=int, default=3)
    noise.add_argument("--concurrency", type=int, default=5)
    add_split(noise)
    noise.set_defaults(func=cmd_noise)

    status = sub.add_parser("status", help="show labeling progress across all cases")
    status.add_argument("--todo", action="store_true", help="only unfinished cases")
    status.set_defaults(func=cmd_status)

    pre = sub.add_parser("prelabel", help="propose candidates for human adjudication")
    pre.add_argument("--case", required=True, help="case id, e.g. clean_002")
    pre.add_argument("--model", default="claude-opus-5")
    pre.add_argument("--phase", choices=["competitors", "forbidden", "both"],
                     default="both")
    pre.set_defaults(func=cmd_prelabel)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
