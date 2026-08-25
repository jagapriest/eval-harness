"""Build the dev/test split.

Stratified by bucket so every bucket appears in both halves -- an unstratified random
split at n=48 can easily put all four `long` cases on one side and leave the other
unable to report that bucket at all.

Deterministic: the same dataset always produces the same split, so a committed results
file stays comparable across runs.

**Unadjudicated cases are excluded.** A case whose `expected.competitors` is empty
because nobody has labeled it yet is indistinguishable, at scoring time, from a case
that is correctly empty -- and it would score every correct extraction as a false
positive. Excluding them is the difference between a small dataset and a wrong one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEV_FRACTION = 0.3
ZERO_COMPETITOR_BUCKETS = {"empty", "adversarial"}  # kept for callers; see is_adjudicated


@dataclass
class SplitResult:
    dev: list[str] = field(default_factory=list)
    test: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    by_bucket: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "dev": sorted(self.dev),
            "test": sorted(self.test),
            "excluded": self.excluded,
            "by_bucket": self.by_bucket,
            "note": (
                "Stratified by bucket, deterministic by case_id hash. The test split is "
                "held out: touch it twice across the project, once mid-build and once at "
                "the end. Never tune against it."
            ),
        }


def is_adjudicated(case: dict) -> tuple[bool, str]:
    """Has a human decided this case, on both phases?

    A zero-candidate phase counts as decided -- there was nothing to adjudicate. What
    does not count is a phase with candidates and no provenance key.
    """
    expected = case.get("expected", {})
    screening = case.get("screening", {})

    if screening.get("proposed") and "prelabel" not in expected:
        return False, "competitors not adjudicated"
    if screening.get("proposed_must_not_include") and "prelabel_forbidden" not in expected:
        return False, "must_not_include not adjudicated"

    # Deliberately no "this bucket ought to have competitors" rule. `long` is defined
    # by word count alone -- Dell and NetApp at 9,000 words genuinely name none, and
    # excluding them would drop the two most interesting long cases. Bucket/label
    # mismatch is a question for `audit`, which reports it as a warning; it is not
    # evidence that a human failed to look at the case.
    return True, ""


def _rank(case_id: str) -> int:
    """Stable pseudo-random ordering. Deterministic across machines and runs."""
    return int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)


def build_split(root: Path | None = None, dev_fraction: float = DEV_FRACTION) -> SplitResult:
    root = root or ROOT
    result = SplitResult()
    by_bucket: dict[str, list[str]] = {}

    for path in sorted((root / "data" / "cases").glob("*.json")):
        case = json.loads(path.read_text())
        ok, reason = is_adjudicated(case)
        if not ok:
            result.excluded[case["case_id"]] = reason
            continue
        by_bucket.setdefault(case["bucket"], []).append(case["case_id"])

    for bucket, ids in sorted(by_bucket.items()):
        ordered = sorted(ids, key=_rank)
        # At least one dev case per bucket, and never the whole bucket -- both halves
        # must be able to report every bucket.
        n_dev = max(1, round(len(ordered) * dev_fraction))
        n_dev = min(n_dev, len(ordered) - 1) if len(ordered) > 1 else len(ordered)
        result.dev.extend(ordered[:n_dev])
        result.test.extend(ordered[n_dev:])
        result.by_bucket[bucket] = {"dev": n_dev, "test": len(ordered) - n_dev}

    return result


def write(result: SplitResult, root: Path | None = None) -> Path:
    root = root or ROOT
    path = root / "data" / "splits.json"
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
    return path


def summarize(result: SplitResult) -> str:
    lines = ["", f"{'bucket':14s} {'dev':>5s} {'test':>5s} {'total':>6s}", "-" * 34]
    for bucket, counts in result.by_bucket.items():
        total = counts["dev"] + counts["test"]
        lines.append(f"{bucket:14s} {counts['dev']:5d} {counts['test']:5d} {total:6d}")
    lines += [
        "-" * 34,
        f"{'TOTAL':14s} {len(result.dev):5d} {len(result.test):5d} "
        f"{len(result.dev) + len(result.test):6d}",
    ]
    if result.excluded:
        lines += ["", f"  excluded ({len(result.excluded)}) -- not yet adjudicated:"]
        for case_id, reason in sorted(result.excluded.items()):
            lines.append(f"    {case_id:18s} {reason}")
        lines.append("    Re-run after labeling to fold them in.")
    lines.append("")
    return "\n".join(lines)
