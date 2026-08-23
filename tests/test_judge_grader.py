"""US-006 -- judge grader.

No live API calls in the default run: the client is faked. The one test that must
observe real cache behavior is marked `live` and excluded by default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pytest

from src.graders.judge_grader import (
    AXES,
    JudgeError,
    JudgeScores,
    build_request,
    judge,
    load_rubric,
    median_scores,
    parse_scores,
    render_prompt,
)
from src.schema import Competitor, Confidence, Extraction

DOCUMENT = "Our competitors include Dell Technologies Inc. and Lenovo Group Ltd."

EXTRACTION = Extraction(
    competitors=[
        Competitor(name="Dell Technologies", evidence="competitors include Dell",
                   confidence=Confidence.high)
    ],
    summary="The company competes with established infrastructure vendors.",
)

EMPTY_EXTRACTION = Extraction(competitors=[], summary="The document names no competitors.")


# --------------------------- fake client ---------------------------

@dataclass
class FakeUsage:
    input_tokens: int = 1000
    output_tokens: int = 100
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list
    usage: FakeUsage


class FakeMessages:
    def __init__(self, payloads, usages=None):
        self.payloads = list(payloads)
        self.usages = list(usages) if usages else None
        self.requests = []
        self.calls = 0

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        text = self.payloads[min(self.calls, len(self.payloads) - 1)]
        usage = (
            self.usages[min(self.calls, len(self.usages) - 1)]
            if self.usages else FakeUsage()
        )
        self.calls += 1
        return FakeResponse(content=[FakeBlock(text=text)], usage=usage)


class FakeClient:
    def __init__(self, payloads, usages=None):
        self.messages = FakeMessages(payloads, usages)


def scored(f=5, r=5, c=5, reasoning="because"):
    return json.dumps(
        {"reasoning": reasoning, "faithfulness": f, "relevance": r, "concision": c}
    )


# --------------------------- rubric ---------------------------

def flat(text: str) -> str:
    """Collapse whitespace before phrase matching.

    The rubric is hard-wrapped, so a phrase that reads as one line in the source may
    contain a newline. Searching the raw text silently fails on wrap position -- the
    same class of bug that pagination artifacts caused in evidence checking.
    """
    return re.sub(r"\s+", " ", text).lower()


def test_rubric_forbids_grading_the_competitor_set():
    """Using a judge where a rule works is the most common eval design error."""
    rubric = flat(load_rubric())
    assert "not evaluating which companies were extracted" in rubric
    assert "graded separately by exact rules" in rubric
    assert "judge only the writing" in rubric


def test_rubric_requires_reasoning_before_score():
    rubric = flat(load_rubric())
    assert "reason first" in rubric
    assert "must come before the numbers" in rubric


def test_rubric_has_all_five_levels_for_every_axis():
    rubric = load_rubric()
    for axis in AXES:
        section = rubric.split(f"### {axis.capitalize()}")[1].split("###")[0]
        for level in range(1, 6):
            assert f"**{level}**" in section, f"{axis} missing level {level}"


def test_rubric_has_worked_examples():
    assert load_rubric().count("Worked example") >= 3


def test_rubric_protects_the_correct_empty_answer():
    """3 of 5 spike documents name no competitors. A correct 'none' must score well."""
    rubric = flat(load_rubric())
    assert "names no competitors" in rubric
    assert "deserves 5s" in rubric


def test_render_prompt_substitutes_every_placeholder():
    prompt = render_prompt(load_rubric(), DOCUMENT, EXTRACTION)
    assert "{{DOCUMENT}}" not in prompt
    assert "{{SUMMARY}}" not in prompt
    assert "{{EVIDENCE}}" not in prompt
    assert DOCUMENT in prompt
    assert EXTRACTION.summary in prompt
    assert "Dell Technologies" in prompt


def test_render_prompt_marks_an_empty_extraction_explicitly():
    prompt = render_prompt(load_rubric(), DOCUMENT, EMPTY_EXTRACTION)
    assert "(none - the extraction returned no competitors)" in prompt


# --------------------------- request shape ---------------------------

def test_request_never_sets_temperature():
    """temperature/top_p/top_k are removed on current models and return HTTP 400."""
    request = build_request("prompt", "claude-opus-5")
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in request


def test_request_places_a_cache_breakpoint_on_the_prompt():
    request = build_request("prompt", "claude-opus-5")
    block = request["messages"][0]["content"][0]
    assert block["cache_control"] == {"type": "ephemeral"}


def test_effort_goes_inside_output_config():
    assert build_request("p", "m", effort="high")["output_config"] == {"effort": "high"}


def test_effort_omitted_when_none():
    assert "output_config" not in build_request("p", "m", effort=None)


# --------------------------- parsing ---------------------------

def test_parse_direct_json():
    s = parse_scores(scored(4, 5, 3, "reasoning here"))
    assert (s.faithfulness, s.relevance, s.concision) == (4, 5, 3)
    assert s.reasoning == "reasoning here"


def test_parse_fenced_json():
    assert parse_scores(f"```json\n{scored(3, 3, 3)}\n```").faithfulness == 3


def test_parse_json_wrapped_in_prose():
    assert parse_scores(f"Here is my assessment.\n{scored(2, 2, 2)}\nDone.").relevance == 2


@pytest.mark.parametrize("bad", ["not json", "", "{}"])
def test_unparseable_or_incomplete_output_raises(bad):
    with pytest.raises(JudgeError):
        parse_scores(bad)


def test_out_of_range_score_raises():
    with pytest.raises(JudgeError, match="out of range"):
        parse_scores(json.dumps({"faithfulness": 9, "relevance": 3, "concision": 3}))


def test_non_integer_score_raises():
    with pytest.raises(JudgeError, match="not an integer"):
        parse_scores(json.dumps({"faithfulness": "good", "relevance": 3, "concision": 3}))


def test_missing_axis_raises():
    with pytest.raises(JudgeError, match="concision"):
        parse_scores(json.dumps({"faithfulness": 3, "relevance": 3}))


# --------------------------- median ---------------------------

def test_median_is_per_axis():
    samples = [
        JudgeScores(5, 1, 3),
        JudgeScores(3, 5, 3),
        JudgeScores(4, 3, 4),
    ]
    m = median_scores(samples)
    assert (m.faithfulness, m.relevance, m.concision) == (4, 3, 3)


def test_median_resists_a_single_outlier():
    """The reason for 3 calls: one wild sample must not move the estimate."""
    m = median_scores([JudgeScores(5, 5, 5), JudgeScores(5, 5, 5), JudgeScores(1, 1, 1)])
    assert (m.faithfulness, m.relevance, m.concision) == (5, 5, 5)


def test_median_of_empty_raises():
    with pytest.raises(JudgeError):
        median_scores([])


# --------------------------- end to end (faked) ---------------------------

async def test_judge_makes_three_calls_and_returns_the_median():
    client = FakeClient([scored(5, 5, 5), scored(3, 4, 5), scored(4, 4, 4)])
    result = await judge(DOCUMENT, EXTRACTION, client=client)
    assert client.messages.calls == 3
    assert (result.scores.faithfulness, result.scores.relevance) == (4, 4)
    assert len(result.samples) == 3


async def test_sample_count_is_configurable():
    client = FakeClient([scored()])
    result = await judge(DOCUMENT, EXTRACTION, client=client, samples=5)
    assert client.messages.calls == 5
    assert len(result.samples) == 5


async def test_sample_spread_reports_judge_instability():
    client = FakeClient([scored(5, 5, 5), scored(1, 5, 5), scored(3, 5, 5)])
    result = await judge(DOCUMENT, EXTRACTION, client=client)
    assert result.sample_spread["faithfulness"] == 4
    assert result.sample_spread["relevance"] == 0


async def test_all_three_requests_are_byte_identical():
    """They must be, or calls 2 and 3 cannot hit the cache."""
    client = FakeClient([scored()])
    await judge(DOCUMENT, EXTRACTION, client=client)
    first, *rest = client.messages.requests
    assert all(r == first for r in rest)


async def test_usage_is_accumulated_across_samples():
    usages = [
        FakeUsage(input_tokens=1000, cache_creation_input_tokens=900),
        FakeUsage(input_tokens=100, cache_read_input_tokens=900),
        FakeUsage(input_tokens=100, cache_read_input_tokens=900),
    ]
    client = FakeClient([scored()], usages)
    result = await judge(DOCUMENT, EXTRACTION, client=client)
    assert result.cache_read_tokens == 1800
    assert result.cache_write_tokens == 900


@pytest.mark.live
async def test_cache_is_actually_read_on_calls_two_and_three():
    """Requires a live API key. Excluded from the default run.

    Run with: pytest -m live
    """
    import anthropic

    from src.cli import load_env

    load_env()
    result = await judge(
        DOCUMENT * 400,  # exceed the ~1024-token minimum cacheable prefix
        EXTRACTION,
        client=anthropic.AsyncAnthropic(),
    )
    assert result.cache_read_tokens > 0, "no cache hit; a silent invalidator is at work"
