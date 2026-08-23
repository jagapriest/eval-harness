"""Measure run-to-run variance of a config on a fixed dataset.

There is no seed parameter in the Messages API, so output is non-deterministic by
construction. A regression is only a regression if it exceeds this floor -- which
means the floor has to be measured before any config comparison means anything.

The spike measured a macro-F1 spread of 0.40 across three identical runs at n=5, with
all of it concentrated in cases where the correct answer is "extract nothing".
"""

from __future__ import annotations

import asyncio
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .grade import grade_case, load_cases
from .graders.set_grader import load_aliases
from .metrics import Report, build_report
from .runner import RunConfig, run_all

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class NoiseResult:
    config_id: str
    split: str | None
    replicates: int
    macro_f1: list[float] = field(default_factory=list)
    per_case: dict[str, list[float]] = field(default_factory=dict)
    per_case_extractions: dict[str, list[int]] = field(default_factory=dict)
    cost_usd: float = 0.0

    @property
    def floor(self) -> float:
        """Macro-F1 spread across replicates. This is the number that gates US-010."""
        return max(self.macro_f1) - min(self.macro_f1) if len(self.macro_f1) > 1 else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.macro_f1) if len(self.macro_f1) > 1 else 0.0

    @property
    def mean(self) -> float:
        return statistics.mean(self.macro_f1) if self.macro_f1 else 0.0

    def unstable_cases(self, threshold: float = 0.5) -> dict[str, float]:
        """Cases whose F1 swings more than `threshold` across identical runs."""
        spreads = {
            cid: max(vals) - min(vals)
            for cid, vals in self.per_case.items() if len(vals) > 1
        }
        return {cid: s for cid, s in sorted(spreads.items(), key=lambda kv: -kv[1])
                if s > threshold}

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "split": self.split,
            "replicates": self.replicates,
            "macro_f1": self.macro_f1,
            "mean": self.mean,
            "stdev": self.stdev,
            "noise_floor": self.floor,
            "per_case_f1": self.per_case,
            "per_case_extractions": self.per_case_extractions,
            "unstable_cases": self.unstable_cases(),
            "cost_usd": self.cost_usd,
        }


def measure(
    cfg: RunConfig,
    replicates: int = 3,
    split: str | None = None,
    concurrency: int = 5,
    root: Path | None = None,
) -> NoiseResult:
    root = root or ROOT
    cases = load_cases(split, root)
    aliases = load_aliases(root / "data" / "aliases.json")
    result = NoiseResult(config_id=cfg.id, split=split, replicates=replicates)

    for _ in range(replicates):
        # use_cache=False is mandatory here: caching would return the same response
        # every time and report a noise floor of exactly zero.
        responses = asyncio.run(
            run_all([(c["case_id"], c["document"]) for c in cases], cfg,
                    concurrency=concurrency, use_cache=False)
        )
        by_id = {r.case_id: r for r in responses}
        f1s = []
        for case in cases:
            response = by_id[case["case_id"]]
            result.cost_usd += response.cost(cfg)
            outcome = grade_case(case, response.raw_text, aliases)
            result.per_case.setdefault(case["case_id"], []).append(outcome.f1)
            result.per_case_extractions.setdefault(case["case_id"], []).append(
                outcome.n_predicted
            )
            f1s.append(outcome.f1)
        result.macro_f1.append(statistics.mean(f1s) if f1s else 0.0)

    return result


def write(result: NoiseResult, path: Path | None = None, root: Path | None = None) -> Path:
    root = root or ROOT
    path = path or root / "results" / "noise_floor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
    return path


def read_floor(path: Path | None = None, root: Path | None = None) -> float:
    """Read the measured floor. Raises if it has not been measured."""
    root = root or ROOT
    path = path or root / "results" / "noise_floor.json"
    if not path.exists():
        raise FileNotFoundError(
            f"noise floor not measured: {path} is missing. "
            "Run: python -m src.cli noise --config baseline"
        )
    return float(json.loads(path.read_text())["noise_floor"])


def summarize(result: NoiseResult) -> str:
    lines = [
        f"\nconfig '{result.config_id}' x{result.replicates}"
        + (f" on split '{result.split}'" if result.split else ""),
        "",
        f"  macro-F1 : {[round(v, 3) for v in result.macro_f1]}",
        f"  mean     : {result.mean:.3f}",
        f"  stdev    : {result.stdev:.3f}",
        f"  SPREAD   : {result.floor:.3f}   <-- noise floor",
        "",
        "  A config delta must exceed this to count as a regression.",
    ]
    unstable = result.unstable_cases()
    if unstable:
        lines += ["", "  unstable cases (F1 spread > 0.5 across identical runs):"]
        for cid, spread in unstable.items():
            lines.append(
                f"    {cid:20s} spread {spread:.2f}  "
                f"extractions {result.per_case_extractions.get(cid)}"
            )
    lines += ["", f"  cost: ${result.cost_usd:.4f}", ""]
    return "\n".join(lines)


def report_for(cfg: RunConfig, split: str | None = None, root: Path | None = None) -> Report:
    """Convenience: single-run graded report, used by the CLI's grade/report paths."""
    root = root or ROOT
    cases = load_cases(split, root)
    aliases = load_aliases(root / "data" / "aliases.json")
    responses = asyncio.run(
        run_all([(c["case_id"], c["document"]) for c in cases], cfg, concurrency=5)
    )
    by_id = {r.case_id: r for r in responses}
    outcomes = [
        grade_case(c, by_id[c["case_id"]].raw_text, aliases,
                   by_id[c["case_id"]].cost(cfg), by_id[c["case_id"]].latency_s)
        for c in cases
    ]
    return build_report(cfg.id, outcomes)
