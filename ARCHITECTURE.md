# Architecture

How the harness is put together, and why each decision was made that way. Most of the
rationale below is downstream of something the spike measured — see
[`writeup/spike-findings.md`](writeup/spike-findings.md).

---

## Data flow

```
  configs/*.yaml ──► config.load_named ──► RunConfig
                                             │
  data/docs/*.txt ─────────────────┐         │
  data/cases/*.json ──► grade.load_cases     │
                                   │         │
                                   ▼         ▼
                              runner.run_all ──► cache hit? ──► results/cache/*.json
                                   │                 │ no
                                   │                 ▼
                                   │           Messages API ──► results/raw/*.json
                                   ▼
                             grade.grade_case
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
       schema_grader         set_grader           judge_grader
       valid? how parsed?    P / R / F1           faithfulness
       evidence ≤25 words    forbidden hits       relevance
                             near-miss            concision
                             verbatim / near      (prose only)
              └────────────────────┼────────────────────┘
                                   ▼
                             metrics.CaseOutcome
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
            metrics.build_report          grade.outcomes_to_jsonl
            bucket breakout               results/*.jsonl
            bootstrap CIs                 (the run-to-run diff
                     │                     IS the regression signal)
                     ▼
              report.write_report ──► report.md + 2 charts
```

---

## Modules

| Module | Responsibility |
|---|---|
| `schema.py` | Pydantic models and the JSON Schema handed to `output_config.format` |
| `config.py` | YAML → `RunConfig`, with validation that fails loudly |
| `runner.py` | Cached async execution, concurrency cap, retry with backoff |
| `grade.py` | The seam: raw response + labeled case → `CaseOutcome` |
| `metrics.py` | Aggregation, bucket breakout, bootstrap CIs, noise-floor gate |
| `noise.py` | Run-to-run variance measurement |
| `report.py` | Markdown and exactly two charts |
| `prelabel.py` | Model-proposed candidates, human adjudication |
| `graders/` | The three graders, in ascending cost |

`grade.py` exists as its own module rather than living in the CLI because three callers
need it — the CLI, the noise measurement, and the regression test — and **the
regression test must reach it without importing anything that touches the network.**

---

## The three graders, in ascending cost

### 1. Schema grader — deterministic

Pass/fail on valid JSON, required keys, confidence enum, and the 25-word evidence cap.

It also records **how** the JSON was recovered: `direct`, `fence`, `regex`, or `failed`.
This matters because the production `bank-intelligence` function does `JSON.parse()`
with a regex fallback, and the spike watched that fallback fire *intermittently on the
same prompt and model* — run 1 needed a markdown-fence strip on the largest case, run 2
did not. An undocumented, intermittently load-bearing fallback is the worst kind to
have, so the parse path is reported alongside validity.

### 2. Set grader — deterministic

Precision, recall, F1 against the labeled expectation, plus a separately tracked
false-positive rate on `must_not_include`.

Three design choices worth naming:

**Near-miss is a third outcome.** An extraction close to an expected name but unequal
under normalization is reported as a near-miss, not silently counted as a false
positive. That is how set graders quietly lie about precision.

**Normalization strips more than corporate suffixes.** Parenthetical glosses and slash
pairs are collapsed too, because models render the same entity several ways:

```
International Business Machines Corporation (IBM)  ─┐
IBM                                                 ├─► international business machines
                                                    ┘
Broadcom/VMware  ──► broadcom  ◄── Broadcom
```

Both forms were observed in real output. Before this, a three-year competitor diff
reported the same company as a drop *plus* an add, inflating churn by 7 points.

**Evidence verbatim-ness lives here, not in the judge.** The spec originally routed
"evidence quality" to the LLM judge. That bundles two different things: *is this span
in the document* is a substring check, and *does it support the claim* is judgment.
Exact and near-verbatim (≥0.95) are graded as distinct outcomes — collapsing them
either manufactures failures or hides real ones. The spike found a faithful partial
quote that started mid-phrase to fit the word cap: not a contiguous substring, but not
an error either.

### 3. Judge grader — LLM-as-judge, prose only

Faithfulness, relevance, and concision, 1–5, with all five levels defined per axis and
three worked examples.

The rubric **explicitly forbids grading the competitor set**. That is already
deterministic, and using a judge where a rule works is the most common eval design
error.

Three calls, per-axis median. Note there is deliberately **no `temperature`** —
`temperature`, `top_p`, and `top_k` are removed on current models and return HTTP 400.
Variance comes from repeated calls, not sampling parameters.

The calls run **sequentially, not concurrently**: the first must land before the others
so they read a warmed cache rather than three racing to write it. A test asserts all
three requests are byte-identical, which is the precondition for any cache hit at all.

The rubric also protects the correct-empty answer. Three of five spike documents name
no competitors; a judge that penalized a short, correct "the document names none" would
invert the empty bucket entirely.

---

## Caching

Cache key is `sha256(document + model + effort + structured_output + thinking +
max_tokens + prompt_template)` — everything that can change the output.

Two consequences the project depends on:

1. **Re-running a scored config is free.** Verified: a full `run --config baseline`
   completed 5/5 from cache at zero cost.
2. **`pytest` runs offline.** The dev-split cache is committed, so a reviewer can clone
   and verify the harness in seconds without an API key. That converts the repo from
   "code I'm told works" into "code that demonstrably works."

Every raw request and response is also written to `results/raw/`. When a number looks
wrong you need the transcript, not a summary — that is how three of the five
harness-fault bugs were found.

---

## Non-determinism

**There is no seed parameter in the Messages API.** Output is non-deterministic by
construction, so the spec's "fix all seeds" is not achievable. What *is* achievable:

- measure the run-to-run floor (`src/cli.py noise`)
- publish it in the report
- gate the regression test on it (`metrics.exceeds_noise_floor`)

The spike measured a macro-F1 spread of **0.40 across three identical runs** at n=5.
Critically, the variance was **structural, not uniform**: the hardest recall case scored
35/35 three times running, while all the instability sat in cases where the correct
answer is "extract nothing" and the prompt never said whether *categories* counted.

That is not model instability. It is specification ambiguity, and it is measurable —
which makes it the sharpest thing the `structured` config can be tested against.

`noise.measure()` forces `use_cache=False`. Caching would replay one response three
times and report a noise floor of exactly zero.

---

## Configs

Each config differs from its comparator on **exactly one variable**, and tests assert
it:

```
baseline ──(prompt + output_config.format)──► structured ──(model)──► cheaper
                                                  │
                                                  └──(delete exclusion criteria)──► regressed
```

`regressed` is a plausible "let's shorten this prompt" edit, not sabotage: it deletes
the exclusion criteria and the empty-array example while **keeping** the evidence
rules, so US-010 tests one regression rather than two.

Pricing lives in the config rather than in code, so the cost/quality chart regenerates
identically from a committed results file even after list prices move.

---

## Reporting

Two rules the report enforces structurally rather than by convention:

**No aggregate without its bucket breakout.** `Report.worst_bucket()` names the bucket
an aggregate would hide, and the markdown states it outright — *"aggregate F1 0.50
conceals 0.00 on `adversarial`"*. The reader does not have to go looking.

**No point estimate without an interval.** Bootstrap CIs on every F1, seeded for
reproducibility. At the real n=35 test split, bucket-level F1 rests on 3–15 cases;
`0.88` invites conclusions that `0.88 [0.74–0.96]` does not.

Rates are denominated in **extractions, not cases** — one forbidden hit among 30
extractions is not the same failure as one among one. And an empty case scores
`verbatim_rate` 1.0, not 0.0; it cites no evidence, which is not an evidence failure.
Inverting either would make the empty bucket unreadable.

Anything a run drops is logged in a "Coverage dropped" section. Silent truncation reads
as complete coverage when it is not — the same false-assurance failure that bucket
breakouts exist to prevent.

---

## Manual gates

Three stories are owner-only and marked `manual: true, blocking: true` in
`.claude/prd.json`:

| | |
|---|---|
| **US-001** | Dataset labeling |
| **US-013** | Judge hand-scoring |
| **US-015** | `findings.md` |

These are not preferences. A model-generated golden set, graded by a model, validated
against model-generated hand scores, described in model-generated findings is an
ouroboros — it would measure nothing and would not survive one question about
provenance. `.claude/prompt.md` instructs the implementation loop to halt at each gate
rather than produce a draft "for the owner to edit."

`prelabel.py` is the compromise that keeps this honest: the model *proposes*, the human
*decides*, provenance is recorded on every touched case, and a cold-labeled subset
measures how much the proposals anchored the labeler.

---

## Deliberate omissions

No plugin system. No grader registry. No abstraction over model providers. No second
task. No config inheritance.

This harness evaluates one capability, and the scope discipline is load-bearing: a
framework would have been easier to write, harder to trust, and worth less as evidence
that someone can design an evaluation rather than an architecture.
