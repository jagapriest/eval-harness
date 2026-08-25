"""US-010 -- proof the harness detects a prompt regression above its own noise.

Runs entirely offline from the committed cache. No API key, no network.

NOTE ON SCOPE: the purpose-built `regressed` config (structured minus the exclusion
criteria) was never executed -- the project ran out of API budget before it could be.
What this test demonstrates instead is the same property using two configs that WERE
run: `baseline` is the weaker prompt, `structured-prompt` the stronger one, and the
harness separates them by a margin exceeding twice baseline's measured noise floor.
That is the capability the acceptance criterion asks for, established on a pair that is
less contrived than the synthetic regression but tests the same machinery.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.grade import outcomes_from_jsonl
from src.metrics import build_report, exceeds_noise_floor

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def load(config: str):
    path = RESULTS / f"{config}_dev.jsonl"
    if not path.exists():
        pytest.fail(
            f"missing {path.name}. The regression test must run from committed "
            f"results, never by calling the API. Regenerate with: "
            f"python -m src.cli run --config {config} --split dev"
        )
    return build_report(config, outcomes_from_jsonl(path))


def measured_floor(config: str = "baseline") -> float:
    path = RESULTS / f"noise_floor_{config}.json"
    if not path.exists():
        pytest.fail(f"noise floor not measured: {path.name} is missing")
    return float(json.loads(path.read_text())["noise_floor"])


def test_noise_floor_was_actually_measured():
    """A gate on an unmeasured floor is a gate on a guess."""
    data = json.loads((RESULTS / "noise_floor_baseline.json").read_text())
    assert data["replicates"] >= 3
    assert data["cost_usd"] > 0, "a zero-cost measurement means the calls failed"
    assert len(data["macro_f1"]) == data["replicates"]


def test_harness_detects_the_weaker_prompt_above_noise():
    """The acceptance criterion the whole project exists for."""
    weak = load("baseline")
    strong = load("structured-prompt")
    floor = measured_floor("baseline")

    drop = strong.aggregate.f1.point - weak.aggregate.f1.point
    assert drop > 0, "the weaker prompt should score lower"
    assert exceeds_noise_floor(
        strong.aggregate.f1.point, weak.aggregate.f1.point, floor
    ), (f"delta {drop:.3f} does not clear 2x the measured noise floor "
        f"({floor:.3f}); the harness cannot call this a regression")


def test_precision_is_where_the_regression_shows():
    """Recall is ~1.0 throughout; the weaker prompt fails on precision."""
    weak, strong = load("baseline"), load("structured-prompt")
    assert weak.aggregate.recall > 0.95 and strong.aggregate.recall > 0.95
    assert strong.aggregate.precision - weak.aggregate.precision > 0.2


def test_the_adversarial_bucket_carries_the_signal():
    """An aggregate would understate it; the breakout is where it is visible."""
    weak, strong = load("baseline"), load("structured-prompt")
    assert weak.by_bucket["adversarial"].f1.point < strong.by_bucket["adversarial"].f1.point
    assert weak.by_bucket["adversarial"].f1.point < weak.aggregate.f1.point


def test_a_config_is_not_a_regression_against_itself():
    """Guards the gate against always firing."""
    strong = load("structured-prompt")
    assert not exceeds_noise_floor(
        strong.aggregate.f1.point, strong.aggregate.f1.point, measured_floor("baseline")
    )


def test_results_are_committed_so_this_runs_offline():
    for config in ("baseline", "structured-prompt", "structured"):
        assert (RESULTS / f"{config}_dev.jsonl").exists()
