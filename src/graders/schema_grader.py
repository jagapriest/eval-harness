"""Deterministic schema validation of the raw model output.

Also records *how* the JSON was recovered. The production `bank-intelligence`
function does `JSON.parse(text)` and falls back to a `jsonMatch[0]` regex when that
throws -- so "valid JSON" and "valid JSON on the first try" are different numbers,
and only the second one tells you whether the fallback is load-bearing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..schema import Extraction

MAX_EVIDENCE_WORDS = 25


@dataclass
class SchemaResult:
    valid: bool
    parse_method: str  # "direct" | "fence" | "regex" | "failed"
    errors: list[str]
    extraction: Extraction | None = None
    over_length_evidence: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.over_length_evidence is None:
            self.over_length_evidence = []


def _try_parse(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = text.strip()
    try:
        return json.loads(stripped), "direct"
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip()), "fence"
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0)), "regex"
        except json.JSONDecodeError:
            pass

    return None, "failed"


def grade_schema(raw_text: str) -> SchemaResult:
    payload, method = _try_parse(raw_text)
    if payload is None:
        return SchemaResult(False, method, ["output is not parseable as JSON"])

    errors: list[str] = []
    try:
        extraction = Extraction.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        return SchemaResult(False, method, [f"schema validation failed: {exc}"])

    over_length = [
        c.evidence for c in extraction.competitors
        if len(c.evidence.split()) > MAX_EVIDENCE_WORDS
    ]
    if over_length:
        errors.append(f"{len(over_length)} evidence span(s) exceed {MAX_EVIDENCE_WORDS} words")

    return SchemaResult(
        valid=not errors,
        parse_method=method,
        errors=errors,
        extraction=extraction,
        over_length_evidence=over_length,
    )
