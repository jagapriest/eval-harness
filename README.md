# Competitor Extraction Eval Harness

An evaluation harness for one capability: extracting named competitors from a market
document. Golden dataset, deterministic and LLM-judge grading, judge validation against
hand scores, and a cost/quality frontier across model configurations.

**Success here is not a passing score.** Success is a harness that catches a
deliberately regressed prompt by a margin exceeding its own measured noise floor — and
a writeup honest about what it found.

---

## Status

The harness is built and tested. The dataset is not.

| | |
|---|---|
| Harness | ✅ 208 tests passing, offline |
| Configs | ✅ `baseline`, `structured`, `cheaper`, `regressed` |
| Graders | ✅ schema, set, judge |
| Dataset | ⏳ 48 cases staged from EDGAR, **0 adjudicated** — run `./label` |
| Judge validation | ⏳ blocked on dataset |
| Noise floor (real dev split) | ⏳ blocked on dataset |
| Findings writeup | ⏳ blocked on results |

Progress: [`.claude/prd.json`](.claude/prd.json) · Spike results:
[`writeup/spike-findings.md`](writeup/spike-findings.md)

---

## Reproduce

Runs the full test suite offline from the committed response cache. **No API key
required** — the cache is checked in, so a reviewer can verify the harness works
without signing up for anything.

```bash
python -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q
./.venv/bin/python -m src.cli grade --config baseline
```

The third command re-grades a committed results file and prints the full report —
again, no network. To run against the live API, add a key:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
./.venv/bin/python -m src.cli run --config baseline
```

---

## What the spike found

Five cases, $1.12, before any dataset work. Several assumptions did not survive it.

| Assumption | Measured | Consequence |
|---|---|---|
| Evidence verbatim-ness needs a judge | **98%** exact-substring | Deterministic. Moved out of the judge. |
| Hallucination is the dominant failure | **0** across 49 extractions | Over-extraction is *categories*, not fabrication |
| "Fix all seeds" | No seed parameter exists | Measure the noise floor instead |
| Aggregate F1 is the headline | Noise floor **0.40** at n=5 | No delta below the floor counts |
| Hand labels are ground truth | **17%** label error, all omissions | Model-assisted labeling, disclosed |
| 10-Ks give clean cases | 3 of 5 named zero companies | `clean` needs richer filers |

**The recurring finding is that the harness manufactures its own results.** Five
separate times, a number that looked like a model failure was a grader failure:

- EDGAR pagination artifacts injected mid-sentence cost **14 points** of verbatim accuracy
- Parenthetical and slash renderings (`Broadcom/VMware` vs `Broadcom`) inflated measured competitor churn by **7 points**
- First-pass hand labels missed **5 of 33** named competitors
- A rubric assertion failed on a hard-wrapped line
- `relative_to()` crashed on results written outside the repo

Check the grader before blaming the model.

---

## Commands

```bash
./label                    # labeling progress; what to do next
./label ambiguous_003      # adjudicate a case (works from any directory)
./label clean_004 --phase forbidden

python -m src.cli status   [--todo]
python -m src.cli run      --config baseline [--split dev] [--no-cache]
python -m src.cli grade    --config baseline          # offline, from results file
python -m src.cli report   --config baseline --config structured
python -m src.cli noise    --config baseline [--replicates 3]
python -m src.cli prelabel --case clean_002           # human adjudication loop
```

Supporting scripts:

```bash
python scripts/fetch_edgar.py                         # pull 10-K competition sections
python scripts/competitor_drift.py --cik 0001645590   # diff competitors across years
```

`pytest -m live` runs the handful of tests that need a real API key.

---

## Layout

```
configs/          four YAML configs, each pinning model, effort, prompt, and prices
prompts/          baseline / structured / regressed extraction, plus the judge rubric
data/
  docs/           source documents (real SEC filings)
  cases/          48 staged cases (screening proposals + your adjudicated labels)
  spike_cases/    5 archived provisional cases, superseded
  pool/           screening metadata
  aliases.json    name normalization map
  drift/          multi-year competitor diffs
src/
  schema.py       pydantic models + JSON Schema for structured-output configs
  config.py       YAML -> RunConfig
  runner.py       cached async runner, concurrency cap, retry/backoff
  grade.py        raw response + case -> CaseOutcome  (the seam)
  metrics.py      bucket breakout, bootstrap CIs, noise-floor gate
  noise.py        run-to-run variance measurement
  report.py       markdown + exactly two charts
  prelabel.py     model-assisted labeling with human adjudication
  graders/        schema_grader, set_grader, judge_grader
results/
  cache/          committed response cache — this is what makes pytest offline
writeup/          spike findings, and eventually findings.md
```

---

## Cost

Measured, not estimated.

| | |
|---|---|
| Per case | $0.055 |
| 50 cases × 3 configs | **$8.29** |
| Full project incl. 3× judge | under $50 |
| Spike to date | $1.12 |

Cost should not drive a design decision on this project. Pick a model or a sample size
for methodological reasons, not to save money.

---

## Design decisions

Detail in [`ARCHITECTURE.md`](ARCHITECTURE.md). The short version:

- **Deterministic where deterministic.** The judge grades prose only, never the
  competitor set. Using a judge where a rule works is the most common eval design error.
- **Every metric is broken out by bucket.** An aggregate F1 of 0.88 hiding 0.55 on
  adversarial cases is a false assurance — the exact failure evals exist to prevent.
- **Every point estimate carries an interval.** Bootstrap CIs, seeded so a committed
  results file regenerates identical charts.
- **A regression must clear the measured noise floor.** There is no seed parameter;
  non-determinism is measured, not eliminated.
- **Three steps are owner-only.** Dataset labeling, judge hand-scoring, and the
  findings writeup. A model-generated golden set graded by a model would void the
  artifact.

---

## What is deliberately not here

No plugin system, no abstraction layer, no second task. This evaluates one capability.
The scope discipline is the point — a framework would have been easier and worth less.
