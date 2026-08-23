# PRD: Competitor Extraction Eval Harness

**Owner:** Delvon Jones
**Repo:** `~/code/eval-harness` → `github.com/jagapriest/eval-harness`
**Status:** ready_for_implementation
**Created:** 2026-08-22
**Supersedes:** the design doc at `~/Library/Mobile Documents/com~apple~CloudDocs/PRD-Eval-Harness.md`, which remains the rationale document. This is the story-decomposed implementation plan, revised against measured spike results.

---

## Introduction

An evaluation harness for one capability: extracting named competitors from a market
document. It produces a golden dataset, deterministic and LLM-judge grading, judge
validation against hand scores, and a cost/quality frontier across model
configurations — plus a published writeup.

Two goals, in priority order:

1. **Close a credential gap.** LLM evaluation is a named responsibility on every
   Applied AI req and the only one with no supporting evidence. This produces evidence
   as a working artifact rather than a claim.
2. **Prove the harness detects regressions.** Success is not a passing score. Success
   is a harness that catches a deliberately regressed prompt, and a writeup honest
   about what it found.

**A vertical-slice spike has already run** (`writeup/spike-findings.md`, 5 cases,
$1.12). Its results are load-bearing throughout this document and several original
assumptions did not survive it.

---

## Goals

- 50 labeled cases across five buckets, re-weighted toward where measurement is unstable
- Three graders: schema and set (deterministic), judge (prose only)
- Judge validated against 15 hand-scored cases, agreement reported
- Three configurations scored on a held-out test split, with cost/quality frontier
- A measured noise floor, with the regression test gated on it
- A published writeup, 1,200–2,000 words

---

## What the spike changed

| Original assumption | Measured | Consequence |
|---|---|---|
| `evidence` verbatim-ness needs an LLM judge | 98% exact-substring match | Deterministic. Moves to the set grader. |
| Hallucination is the dominant failure | 0 across 49 extractions | Over-extraction is *categories*, not fabrication |
| "Fix all seeds" | No seed parameter exists | Measure and publish the noise floor instead |
| Aggregate F1 is the headline | Noise floor **0.40** at n=5 | No delta below the floor counts |
| Hand labels are ground truth | 17% label error, all omissions | Model-assisted pre-labeling, disclosed |
| 10-Ks give clean cases | 3 of 5 name zero companies | `clean` needs a different source |
| Variance is uniform | Concentrated in empty/adversarial | Re-weight buckets toward them |

---

## Owner rulings (settled 2026-08-22)

- **R-1 Primary market only.** A competitor competes in the document's *primary*
  market. Adjacent-segment competitors are excluded from `expected`, recorded in
  `notes` for provenance, and **not** added to `must_not_include` — extracting one is
  an out-of-scope error, not a fabrication, and the two must stay distinguishable.
  Measured cost on the HPE case: 7 names excluded, F1 1.00 → 0.89.
- **R-2 Buckets re-weighted** toward empty/adversarial (see FR-3).
- **R-3 Manual steps are blocking gates** in `prd.json`, not omissions.

---

## User Stories

### Phase 1 — Dataset

#### US-001 [MANUAL GATE]: Source and label 50 cases
**Description:** As the owner, I need a golden dataset I personally adjudicated, because the labeling is the expertise and a model-generated golden set would void the artifact.

**Acceptance Criteria:**
- [ ] 50 cases: 10 clean, 12 ambiguous, 15 adversarial, 10 empty, 3 long
- [ ] `clean` cases sourced from analyst comparisons or trade press, **not** 10-Ks
- [ ] `must_not_include` populated on ≥25 cases
- [ ] Every judgment call logged in `notes`, R-1 applied to multi-segment filers
- [ ] ≥10 cases labeled cold (no model assistance) to measure anchoring
- [ ] Cold-vs-adjudicated disagreement rate recorded
- [ ] Split committed: 15 dev / 35 test
- [ ] **Ralph must not label cases. This gate blocks the loop.**

#### US-002: Model-assisted pre-labeling CLI
**Description:** As the owner, I want a tool that proposes candidates for me to accept or reject, so labeling is faster and catches names I would miss by reading.

**Acceptance Criteria:**
- [ ] `python -m src.cli prelabel --case <id>` shows each candidate + evidence span
- [ ] Accepts y / n / ? (defer) per candidate; writes to the case file
- [ ] Records per-case adjudication time to `results/labeling_cost.jsonl`
- [ ] Pre-labeling provenance recorded on each case so it can be disclosed
- [ ] Unit test on a fixture case

### Phase 2 — Harness

#### US-003: Config loader and four YAML configs
**Description:** As a developer, I want configs to carry model, effort, structured-output flag, and pinned pricing so runs are reproducible and cost charts regenerate identically.

**Acceptance Criteria:**
- [ ] `configs/{baseline,structured,cheaper,regressed}.yaml` load into `RunConfig`
- [ ] Each pins model ID, effort, `structured_output`, prompt path, and price table
- [ ] `structured` uses `output_config.format`; `baseline` uses prompt-instructed JSON
- [ ] `cheaper` targets `claude-haiku-4-5` at its own pricing
- [ ] `regressed` = `structured` prompt with exclusion criteria deleted
- [ ] Round-trip test asserts loaded values match the YAML

#### US-004: Set grader unit tests
**Description:** As a developer, I need the set grader tested, because it silently lies when normalization is wrong.

**Acceptance Criteria:**
- [ ] Normalization: `Dell Technologies Inc.` ≡ `Dell`, `HPE` ≡ `Hewlett Packard Enterprise`
- [ ] Near-miss returns a third outcome, not a false positive, at ratio ≥0.85
- [ ] `must_not_include` hits tracked separately from false positives
- [ ] Exact and near-verbatim (≥0.95) evidence graded as distinct outcomes
- [ ] Regression test for the mid-phrase-quote case from the spike
- [ ] Regression test for pagination-artifact normalization

#### US-005: Schema grader unit tests
**Acceptance Criteria:**
- [ ] `direct` / `fence` / `regex` / `failed` parse paths each covered
- [ ] Over-length evidence (>25 words) fails validation and is reported
- [ ] Confidence enum violations rejected
- [ ] Test asserts parse method is recorded, not just validity

#### US-006: Judge grader
**Description:** As a developer, I want an LLM judge for prose only, with a validated rubric.

**Acceptance Criteria:**
- [ ] Grades `summary` and evidence *quality* only — never the competitor set
- [ ] Rubric scores faithfulness / relevance / concision 1–5, worked example per level
- [ ] Requires reasoning before score, in that order
- [ ] 3 calls per case, median taken. **No `temperature`** — removed on current models
- [ ] Document placed first with a `cache_control` breakpoint
- [ ] Test asserts `cache_read_input_tokens > 0` on calls 2 and 3
- [ ] Median-of-3 unit test on synthetic scores

#### US-007: Metrics with bucket breakout and bootstrap CIs
**Acceptance Criteria:**
- [ ] Precision, recall, F1, `must_not_include` rate, schema validity, verbatim rate
- [ ] Every metric broken out by bucket — no aggregate reported without it
- [ ] Bootstrap 95% CI (1,000 resamples) on every F1
- [ ] Cost and p50/p95 latency per config
- [ ] Known-input test asserts CI bounds are stable

#### US-008: Noise-floor measurement as a first-class run mode
**Description:** As the owner, I need the run-to-run floor measured on the real dev split, because a regression is only real if it exceeds it.

**Acceptance Criteria:**
- [ ] `python -m src.cli noise --config baseline --replicates 3` on the dev split
- [ ] Reports per-case and macro-F1 spread and stdev
- [ ] Writes `results/noise_floor.json` consumed by US-010
- [ ] Generalizes `scripts/variance.py`, which currently hardcodes baseline

#### US-009: Report generation
**Acceptance Criteria:**
- [ ] Markdown report: metrics by bucket by config, with CIs
- [ ] Chart 1: F1 by bucket by config, CI bars
- [ ] Chart 2: cost vs F1 frontier
- [ ] Exactly two charts, matplotlib only
- [ ] Any coverage the run drops (top-N, sampling, retries) is logged, not silent

#### US-010: Regression test gated on the measured noise floor
**Description:** As the owner, I need proof the harness catches a regression. This is the acceptance criterion the whole project exists for.

**Acceptance Criteria:**
- [ ] `pytest tests/test_regression.py` compares `baseline` vs `regressed` on dev
- [ ] Asserts the precision drop exceeds `noise_floor × 2` from `results/noise_floor.json`
- [ ] Runs **fully offline** from the committed dev-split cache — no API key required
- [ ] Fails loudly if the cache is missing rather than silently calling the API

#### US-011: CLI
**Acceptance Criteria:**
- [ ] `run`, `grade`, `report`, `noise`, `prelabel` subcommands
- [ ] `python -m src.cli run --config configs/baseline.yaml` works from a clean clone
- [ ] `--no-cache` and `--split {dev,test}` flags
- [ ] End-to-end test on cached fixtures

#### US-012: README and committed cache
**Acceptance Criteria:**
- [ ] Reproduce section is exactly three commands
- [ ] Dev-split response cache committed so `pytest` runs offline in seconds
- [ ] Documents that results are JSONL and the run-to-run diff is the regression signal
- [ ] States the noise floor and what it means for interpreting deltas

### Phase 3 — Judge validation

#### US-013 [MANUAL GATE]: Hand-score 15 cases and report agreement
**Description:** As the owner, I must hand-score the judge's cases myself, because the entire point of validation is that a *human* disagreed at a measurable rate.

**Acceptance Criteria:**
- [ ] 15 cases hand-scored on all three rubric axes before seeing judge output
- [ ] Agreement reported as quadratic-weighted Cohen's kappa, plus exact and ±1 rates
- [ ] If agreement <80%, the rubric is revised — not the model
- [ ] **Ralph must not hand-score. This gate blocks the loop.**

### Phase 4 — Run and analysis

#### US-014: Score three configs on the held-out test split
**Acceptance Criteria:**
- [ ] `baseline`, `structured`, `cheaper` run on the 35-case test split
- [ ] Results committed as timestamped JSONL
- [ ] A second run produces a readable diff
- [ ] Test split touched exactly twice total across the project
- [ ] Explicitly tests the spike's prediction: does `structured` collapse the variance concentrated in empty/adversarial?

### Phase 5 — Writeup

#### US-015 [MANUAL GATE]: findings.md
**Description:** As the owner, I must write this myself. The code is table stakes; the writeup is what a hiring manager reads, and generated prose fails at exactly the sections that matter.

**Acceptance Criteria:**
- [ ] Sections: question, task/definition, dataset, grader design, judge validation, results, **what surprised me**, what I'd do at customer scale
- [ ] Includes "what this harness cannot tell you" — sample size, source bias, single labeler, one capability
- [ ] Discloses model-assisted pre-labeling and the cold-label disagreement rate
- [ ] Reports the noise floor and the 17% first-pass label error plainly
- [ ] 1,200–2,000 words, practitioner tone
- [ ] **Ralph must not write this. This gate blocks the loop.**

---

## Functional Requirements

- **FR-1** The system must cache by SHA-256 of (document + prompt + model + params); re-running a scored config must make zero API calls.
- **FR-2** The system must run async with a concurrency cap and retry-with-backoff on 408/409/429/5xx.
- **FR-3** The dataset must be 50 cases: 10 clean, 12 ambiguous, 15 adversarial, 10 empty, 3 long.
- **FR-4** Every metric must be reported per bucket; no aggregate may be published without its breakout.
- **FR-5** The judge must never grade the competitor set — only `summary` and evidence quality.
- **FR-6** Evidence verbatim-ness must be graded deterministically, with exact and near-verbatim (≥0.95) as distinct outcomes.
- **FR-7** The system must log the raw request and response for every API call.
- **FR-8** Configs must pin model ID and price table; results must record resolved model versions.
- **FR-9** The regression test must run offline from committed cache and be gated on the measured noise floor.
- **FR-10** Document ingestion must strip pagination artifacts before any grading.
- **FR-11** Out-of-scope-segment competitors must be recorded in `notes` and excluded from both `expected` and `must_not_include` (R-1).

---

## Non-Goals

- The full agent loop, other agents, RAG retrieval quality, or any UI
- Comparison against non-Anthropic models
- A plugin system, abstraction layer, or support for a second task — one task only
- Growing the dataset beyond 50 cases
- Automating any of the three manual gates

---

## Technical Considerations

**Already built (spike — harden, don't rebuild):**
`src/schema.py`, `src/runner.py`, `src/graders/set_grader.py`,
`src/graders/schema_grader.py`, `scripts/fetch_edgar.py`, `scripts/variance.py`,
`scripts/spike.py`, `data/aliases.json`, 5 labeled cases.

**Files to create:**
`src/config.py`, `src/graders/judge_grader.py`, `src/metrics.py`, `src/report.py`,
`src/cli.py`, `configs/*.yaml`, `prompts/{structured,regressed,judge}.md`, `tests/*`.

**Constraints:**
- `temperature`/`top_p`/`top_k` are **removed** on current models — a 400. Judge variance comes from 3 plain calls, not sampling params.
- `budget_tokens` is removed; use `output_config.effort`.
- No seed parameter exists. Non-determinism is measured, not eliminated.
- Structured outputs make schema validity near-free — that asymmetry is a finding, not a bug to hide.

**Measured baselines to hold the line against:**
$0.055/case · 98% verbatim · 0 hallucinations/49 · noise floor 0.40 at n=5.

---

## Success Metrics

| Metric | Target |
|---|---|
| Schema validity | 100% |
| Precision | ≥ 0.90 |
| Recall | ≥ 0.85 |
| `must_not_include` false positives | ≤ 2% |
| Judge faithfulness (median) | ≥ 4.0 |
| Judge–human agreement | ≥ 80% |
| Noise floor on the real dev split | measured and published |
| Cost / latency | tracked, not targeted |

**The project succeeds when US-010 passes** — a deliberately regressed prompt is caught
by a margin exceeding the measured noise floor — and `findings.md` is published.

---

## Open Questions

1. Where do `clean` cases come from now that 10-Ks are ruled out — analyst summaries, trade press, or vendor comparison pages? Affects US-001 sourcing time.
2. Does `structured` actually collapse the empty/adversarial variance? Testable in US-014; if it doesn't, the variance is model-level and the writeup's conclusion changes.
3. Is 3 replicates enough for a stable noise floor at n=15 dev, or does it need 5?
4. Should `long` (3 cases) survive at all, or fold into the other buckets? It is the least differentiating bucket and the most expensive to label.
