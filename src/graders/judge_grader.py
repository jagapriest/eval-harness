"""LLM-as-judge for prose only.

Three design rules, each of which the spike or the API made non-negotiable:

1. **The judge never grades the competitor set.** That is deterministic and already
   graded by rule. Using a judge where a rule works is the most common eval design
   error, and it also makes the judge's own validation harder to interpret.
2. **Variance comes from repeated calls, not sampling parameters.** `temperature`,
   `top_p`, and `top_k` are removed on current models and return HTTP 400. Three plain
   calls, median taken.
3. **The document goes first, with a cache breakpoint.** The same document and output
   are sent three times in a row, so calls 2 and 3 read the document from cache at
   roughly a tenth of input cost.
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import anthropic

from ..schema import Extraction

ROOT = Path(__file__).resolve().parent.parent.parent
AXES = ("faithfulness", "relevance", "concision")
MIN_SCORE, MAX_SCORE = 1, 5
DEFAULT_SAMPLES = 3


class JudgeError(RuntimeError):
    pass


@dataclass
class JudgeScores:
    faithfulness: int
    relevance: int
    concision: int
    reasoning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_rubric(path: str | Path | None = None) -> str:
    return Path(path or ROOT / "prompts" / "judge.md").read_text()


def render_prompt(rubric: str, document: str, extraction: Extraction) -> str:
    """Fill the rubric template.

    Evidence spans are listed so the judge can assess them as *support*; whether they
    appear verbatim is checked deterministically elsewhere.
    """
    if extraction.competitors:
        evidence = "\n".join(
            f"- {c.name}: \"{c.evidence}\"" for c in extraction.competitors
        )
    else:
        evidence = "(none - the extraction returned no competitors)"
    return (
        rubric.replace("{{DOCUMENT}}", document)
        .replace("{{SUMMARY}}", extraction.summary or "(empty)")
        .replace("{{EVIDENCE}}", evidence)
    )


def parse_scores(raw_text: str) -> JudgeScores:
    """Parse a judge response, tolerating fences and surrounding prose."""
    text = raw_text.strip()
    payload = None
    for candidate in (
        text,
        (re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL) or [None, None])[1],
        (re.search(r"\{.*\}", text, re.DOTALL) or [None])[0],
    ):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate.strip())
            break
        except (json.JSONDecodeError, AttributeError):
            continue
    if not isinstance(payload, dict):
        raise JudgeError(f"judge output is not parseable JSON: {text[:120]!r}")

    scores: dict[str, int] = {}
    for axis in AXES:
        if axis not in payload:
            raise JudgeError(f"judge output missing axis: {axis}")
        try:
            value = int(payload[axis])
        except (TypeError, ValueError) as exc:
            raise JudgeError(f"{axis} is not an integer: {payload[axis]!r}") from exc
        if not MIN_SCORE <= value <= MAX_SCORE:
            raise JudgeError(f"{axis} out of range 1-5: {value}")
        scores[axis] = value

    return JudgeScores(**scores, reasoning=str(payload.get("reasoning", "")))


def median_scores(samples: Sequence[JudgeScores]) -> JudgeScores:
    """Per-axis median. Single judge calls are unstable; the median is the estimate."""
    if not samples:
        raise JudgeError("no judge samples to aggregate")
    return JudgeScores(
        faithfulness=int(statistics.median(s.faithfulness for s in samples)),
        relevance=int(statistics.median(s.relevance for s in samples)),
        concision=int(statistics.median(s.concision for s in samples)),
        reasoning=samples[0].reasoning,
    )


def build_request(prompt: str, model: str, effort: str | None = "medium") -> dict[str, Any]:
    """Build the judge request.

    The whole prompt is one cached block: it is byte-identical across the three
    samples, so calls 2 and 3 read it from cache. Note there is deliberately no
    `temperature` -- it is removed on current models and returns 400.
    """
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": 2000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }
    if effort:
        request["output_config"] = {"effort": effort}
    return request


@dataclass
class JudgeResult:
    scores: JudgeScores
    samples: list[JudgeScores]
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def sample_spread(self) -> dict[str, int]:
        """Per-axis max-min across samples -- the judge's own instability."""
        return {
            axis: max(getattr(s, axis) for s in self.samples)
            - min(getattr(s, axis) for s in self.samples)
            for axis in AXES
        }


async def judge(
    document: str,
    extraction: Extraction,
    model: str = "claude-opus-5",
    effort: str | None = "medium",
    samples: int = DEFAULT_SAMPLES,
    client: anthropic.AsyncAnthropic | None = None,
    rubric: str | None = None,
) -> JudgeResult:
    """Score prose with `samples` sequential calls, returning the per-axis median.

    Calls run sequentially, not concurrently: the first must land before the others so
    they hit the warmed cache rather than all three racing to write it.
    """
    client = client or anthropic.AsyncAnthropic()
    prompt = render_prompt(rubric or load_rubric(), document, extraction)
    request = build_request(prompt, model, effort)

    collected: list[JudgeScores] = []
    totals = {"cache_read": 0, "cache_write": 0, "input": 0, "output": 0}

    for _ in range(samples):
        response = await client.messages.create(**request)
        text = "".join(
            b.text for b in response.content if getattr(b, "type", "") == "text"
        )
        collected.append(parse_scores(text))
        usage = response.usage
        totals["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        totals["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        totals["input"] += getattr(usage, "input_tokens", 0) or 0
        totals["output"] += getattr(usage, "output_tokens", 0) or 0

    return JudgeResult(
        scores=median_scores(collected),
        samples=collected,
        cache_read_tokens=totals["cache_read"],
        cache_write_tokens=totals["cache_write"],
        input_tokens=totals["input"],
        output_tokens=totals["output"],
    )


def judge_sync(*args: Any, **kwargs: Any) -> JudgeResult:
    return asyncio.run(judge(*args, **kwargs))
