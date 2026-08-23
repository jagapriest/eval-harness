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
    from .prelabel import (
        adjudicate,
        apply_adjudication,
        candidates_from_output,
        format_candidate,
        record_cost,
    )
    from .runner import RunConfig, run_all

    load_env()
    path, case, document = load_case(args.case)

    cfg = RunConfig(
        id="prelabel",
        model=args.model,
        prompt_template=(ROOT / "prompts" / "baseline.md").read_text(),
        effort="high",  # proposing candidates is the one place to spend effort
        structured_output=False,
    )
    results = asyncio.run(run_all([(args.case, document)], cfg, concurrency=1))
    result = results[0]
    if result.error:
        raise SystemExit(f"extraction failed: {result.error}")

    candidates = candidates_from_output(result.raw_text, document)
    if not candidates:
        print(f"{args.case}: model proposed no candidates. Nothing to adjudicate.")
        return 0

    already = set(case["expected"].get("competitors", []))
    fresh = [c for c in candidates if c.name not in already]
    print(f"\n{args.case} ({case['bucket']}): {len(candidates)} proposed, "
          f"{len(fresh)} not already labeled.")
    print("Accept only entities NAMED in the document and competing in its PRIMARY "
          "market (owner ruling R-1).")

    total = len(fresh)
    counter = {"i": 0}

    def prompt(cand) -> str:
        counter["i"] += 1
        try:
            return input(format_candidate(cand, counter["i"], total))
        except EOFError:
            return "?"

    adj = adjudicate(fresh, prompt)
    apply_adjudication(path, adj, cfg.id, result.model_version or cfg.model)
    record_cost(_results_dir() / "labeling_cost.jsonl", args.case, adj)

    print(f"\n{args.case}: +{len(adj.accepted)} accepted, {len(adj.rejected)} rejected, "
          f"{len(adj.deferred)} deferred in {adj.seconds}s")
    if adj.deferred:
        print(f"  deferred (resolve by hand): {', '.join(adj.deferred)}")
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

    pre = sub.add_parser("prelabel", help="propose candidates for human adjudication")
    pre.add_argument("--case", required=True, help="case id, e.g. clean_002")
    pre.add_argument("--model", default="claude-opus-5")
    pre.set_defaults(func=cmd_prelabel)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
