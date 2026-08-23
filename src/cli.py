"""Command-line entry point for the eval harness.

Subcommands are added per user story; `prelabel` lands with US-002 and
`run` / `grade` / `report` / `noise` with US-008 and US-011.
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
    print(
        f"\n{args.case} ({case['bucket']}): {len(candidates)} proposed, "
        f"{len(fresh)} not already labeled."
    )
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
    record_cost(ROOT / "results" / "labeling_cost.jsonl", args.case, adj)

    print(
        f"\n{args.case}: +{len(adj.accepted)} accepted, {len(adj.rejected)} rejected, "
        f"{len(adj.deferred)} deferred in {adj.seconds}s"
    )
    if adj.deferred:
        print(f"  deferred (resolve by hand): {', '.join(adj.deferred)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="LLM eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

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
