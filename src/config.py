"""Load run configurations from YAML into `RunConfig`.

Configs pin the model ID, effort, structured-output flag, prompt file, and a **price
table**. Pricing lives in the config rather than in code so the cost/quality chart
regenerates identically from a committed results file even after list prices change.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .runner import RunConfig

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"

REQUIRED = ("id", "model", "prompt_file", "pricing")
VALID_EFFORT = {"low", "medium", "high", "xhigh", "max", None}


class ConfigError(ValueError):
    """Raised when a config file is missing required fields or has invalid values."""


def load_config(path: str | Path, root: Path | None = None) -> RunConfig:
    root = root or ROOT
    path = Path(path)
    if not path.is_absolute():
        candidate = root / path
        path = candidate if candidate.exists() else path
    if not path.exists():
        raise ConfigError(f"config not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}

    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise ConfigError(f"{path.name}: missing required field(s): {', '.join(missing)}")

    effort = raw.get("effort")
    if effort not in VALID_EFFORT:
        raise ConfigError(
            f"{path.name}: effort must be one of low/medium/high/xhigh/max, got {effort!r}"
        )

    prompt_path = root / raw["prompt_file"]
    if not prompt_path.exists():
        raise ConfigError(f"{path.name}: prompt_file not found: {prompt_path}")
    prompt = prompt_path.read_text()
    if "{{DOCUMENT}}" not in prompt:
        raise ConfigError(
            f"{raw['prompt_file']}: prompt must contain the {{{{DOCUMENT}}}} placeholder"
        )

    pricing = raw["pricing"]
    for key in ("input_per_mtok", "output_per_mtok"):
        if key not in pricing:
            raise ConfigError(f"{path.name}: pricing.{key} is required")

    # Cache pricing follows the documented multipliers unless a config overrides them.
    input_price = float(pricing["input_per_mtok"])
    return RunConfig(
        id=raw["id"],
        model=raw["model"],
        prompt_template=prompt,
        effort=effort,
        structured_output=bool(raw.get("structured_output", False)),
        thinking=bool(raw.get("thinking", False)),
        max_tokens=int(raw.get("max_tokens", 8000)),
        input_per_mtok=input_price,
        output_per_mtok=float(pricing["output_per_mtok"]),
        cache_read_per_mtok=float(pricing.get("cache_read_per_mtok", input_price * 0.1)),
        cache_write_per_mtok=float(pricing.get("cache_write_per_mtok", input_price * 1.25)),
    )


def load_named(name: str, root: Path | None = None) -> RunConfig:
    """Load by bare config name, e.g. 'baseline'."""
    root = root or ROOT
    return load_config(root / "configs" / f"{name}.yaml", root=root)


def available(root: Path | None = None) -> list[str]:
    root = root or ROOT
    return sorted(p.stem for p in (root / "configs").glob("*.yaml"))
