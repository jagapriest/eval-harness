# What I learned building an eval harness

**Status: draft. Delvon — read this before publishing. It carries your name and it
concedes things you need to agree with conceding.**

---

## Read this first

The headline number in this repo — `structured-prompt` scoring **F1 0.99** — is not a
real result, and I want that established before anything else.

Late in the project the golden set was normalized by a machine rule, because first-pass
human labeling turned out to be internally inconsistent. That rule draws on the same
screening output the strong configurations produce. **They are being graded against
their own family's answers.** A 0.99 measures agreement between a model and a label
derived from a model, not extraction quality.

The honest version of the comparison is narrower: `baseline` uses a genuinely different
prompt, so its 0.61 is not self-scored, and the gap between the two is real in
*direction* but inflated in *magnitude*.

Everything below is written with that in mind. The interesting findings here are not
the scores. They are the seven times the harness broke itself.

---

## 1. The question

Every Applied AI role names LLM evaluation as a core responsibility. This was built to
turn that from a claim into an artifact: a harness that can catch a regression in a
structured-extraction prompt, with a golden dataset, deterministic and judge-based
grading, and a cost/quality comparison across configurations.

The task under test: extract named competitors from a market document, with a verbatim
evidence span for each. Source documents are real SEC 10-K competition sections.

---

## 2. Where the definition was ambiguous

Writing "what counts as a competitor" before labeling was the right instinct and still
insufficient. Three ambiguities only surfaced against real filings:

**Multi-segment filers.** HPE's 10-K names competitors for enterprise infrastructure
*and* for its IT-asset-disposal and equipment-financing arms. The spec says "the
document's primary market," which excludes the latter — but the document explicitly
calls them "our primary ITAD competitors." Ruling: primary market only. It cost 7 of 35
names on that case and moved F1 from 1.00 to 0.89. **A definitional choice moved the
metric more than most configuration changes would.**

**Categories versus names.** Most filings describe competitor *kinds*, not companies:
"large enterprise software companies, government contractors, and system integrators."
Baseline emitted these as entries, honestly self-labeled `(unnamed)`. Under a spec
requiring a named commercial entity they are precision failures — but the baseline
prompt never said so, which turned out to be the single largest source of variance.

**Partner and competitor at once.** Snowflake names AWS as a competitor while running on
it. NVIDIA names Samsung as both competitor and supplier. This is the genuinely hard
case, and no count-based heuristic finds it — it needs role information.

---

## 3. The dataset, and what is unrepresentative about it

48 cases from SEC 10-K filings across hardware, semiconductors, software, security and
cloud. Buckets: 14 clean, 8 ambiguous, 13 adversarial, 9 empty, 4 long.

Sourcing was automated: a screening pass over 44 filers, extracting competitors, then a
second cheap pass extracting every named organization and its role. Filings sorted
themselves into buckets by how many competitors they named. Cost: $3.26.

**What is unrepresentative:**

- **Source monoculture.** Every document is an SEC filing. One genre, one register, one
  legal incentive structure. Competitor lists in a 10-K are self-reported and shaped by
  what a company wants to disclose. An analyst report or trade-press comparison would
  look nothing like this, and none are included.
- **Small.** 48 cases, 14 dev and 34 test. Bucket-level results rest on 2–10 cases.
  Every interval in the report is wide and should be read as such.
- **Partly machine-derived labels.** See §5.
- **Not independent.** Two `long` cases are the same filers as two shorter cases, at a
  wider window. Same document, different crop.

---

## 4. Grader design

Three graders, in ascending cost, and the interesting decisions are about what does
*not* go to the judge.

**Schema (deterministic).** Valid JSON, required keys, confidence enum, 25-word evidence
cap. It also records *how* the JSON was recovered — direct, markdown fence, or regex.
That turned out to matter: see §6.

**Set (deterministic).** Precision, recall, F1, with `must_not_include` tracked
separately. Near-miss is a third outcome beside match and miss, because counting a
normalization failure as a false positive is how a set grader quietly lies.

**Evidence verbatim-ness moved out of the judge.** The original spec sent "evidence
quality" to the LLM judge. That bundles two different questions: *is this span in the
document* is a substring check; *does it support the claim* is judgment. Measured
verbatim rate is **98%** — models quote accurately, and the one miss was a faithful
partial quote that started mid-phrase to fit the word cap. Exact and near-verbatim
(≥0.95) are scored separately.

**Judge (LLM), prose only.** Faithfulness, relevance, concision, three calls, per-axis
median. Note there is no `temperature` anywhere: it is removed on current models and
returns HTTP 400. Judge variance comes from repeated calls, not sampling parameters.

---

## 5. The labels were the weakest part of the project

This is the section I would most want a reader to take seriously.

**First pass, model-assisted:** a screener proposed candidates, a human accepted or
rejected each. Accept rate across cases ranged from **0% to 100% on structurally similar
filings** — 28 of 28 accepted on HPE, 0 of 20 on Marvell in 22 seconds. Intel and Nvidia
were rejected as competitors on AMD's own filing. SAP, Salesforce and Workday were
rejected on Oracle's.

The evaluation caught it, but only indirectly: **recall was 1.00 on every case in every
configuration.** All measured error was precision — and precision was being computed
against labels that reject Intel-on-AMD. The eval was measuring the labeler.

**Second pass, normalized.** One stated rule applied uniformly: accept a proposed
competitor if it is findable in the source document and the entities pass did not assign
it a non-competitor role. Empty and adversarial buckets keep empty lists by definition.
Label count went **144 → 299**, changing 20 of 48 cases.

Original labels are preserved verbatim under `expected_as_labeled` and scored alongside.
The delta is reported rather than resolved silently.

**The cost of that decision, stated plainly:** the rule uses machine signals, so 26 of 48
cases now carry `normalized-only` provenance and 22 carry `human+normalized`. Any
configuration resembling the screener scores better for that reason alone. This is why
0.99 is not a real number. A dataset built to a deadline is a dataset with a caveat.

**What I would do differently:** budget labeling time first and build to it, rather than
building the harness first and labeling against the clock. Measure intra-labeler
agreement early — relabel ten cases blind after a break and check yourself against
yourself — because a labeler drifting is invisible from inside the task.

---

## 6. What surprised me

**The harness broke itself seven times, and every break looked like a model failure.**

1. **EDGAR pagination artifacts** (`10 Table of Contents`) injected mid-sentence broke
   verbatim matching. Fixing the document pipeline moved measured accuracy **83.6% →
   98.0%** with no change to model, prompt, or config. A 14-point swing that was
   entirely mine.
2. **Name normalization** missed parenthetical and slash forms, so
   `International Business Machines Corporation (IBM)` and `IBM` scored as two
   companies. Inflated measured competitor churn by 7 points.
3. **First-pass labels** missed 5 of 33 named competitors on one case (17%).
4. **A rubric assertion** failed on a hard-wrapped line — same whitespace class as (1).
5. **`relative_to()`** crashed on results written outside the repo, failing runs that had
   already succeeded.
6. **`effort` on Haiku** returns HTTP 400. The `cheaper` config shipped with it set;
   every case of that comparison would have failed at run time.
7. **A billing outage produced a perfect 0.000 noise floor.** Every call returned 400,
   every response body was empty, and an empty extraction scores 1.0 on empty cases and
   0.0 on clean ones — a rock-stable, entirely fictional macro-F1 of exactly 0.500 across
   three runs. I nearly wrote it up as the headline finding.

That last one is the most dangerous number this project produced. **Determinism from
total failure looks exactly like excellence.** Both paths now abort rather than average,
with a regression test.

**The other real surprise: hallucination never happened.** Three of five spike documents
name no competitors at all and instead describe categories — textbook bait for
training-knowledge leakage. Across 49 extractions: **zero** fabricated company names. When
the model over-extracted it emitted categories, honestly self-labeled `(unnamed)`. That is
a different failure needing a different fix, and `must_not_include` was designed for the
wrong one.

**And a finding about the eval itself:** an unstable reference configuration makes the
eval blind. Baseline's run-to-run spread is 0.140–0.288; `structured-prompt`'s is 0.004.
A comparison anchored on baseline cannot detect a delta below ~0.28. Fixing the prompt did
not only improve the score — it made the harness *capable of detecting regressions at all*.

---

## 7. Results

Dev split, n=14, normalized labels. **Read §5 before reading this table.**

| Config | F1 (95% CI) | Precision | Recall | Schema | Verbatim | Cost | p50 |
|---|---|---|---|---|---|---|---|
| `baseline` | 0.61 [0.35–0.84] | 0.59 | 1.00 | 93% | 95.1% | $0.88 | 9.8s |
| `structured-prompt` | 0.99 [0.97–1.00] | 0.98 | 1.00 | 79% | 99.0% | $0.88 | 6.0s |
| `structured` | 0.99 [0.97–1.00] | 0.98 | 1.00 | 79% | 99.0% | $0.86 | 6.5s |

Bucket breakouts hide nothing: `baseline`'s 0.61 conceals **0.25 on adversarial**.

**The one result I trust most is not in the table.** JSON recovery:

| Config | direct | fence | regex |
|---|---|---|---|
| `baseline` | 14 | 0 | 0 |
| `structured-prompt` | 3 | **11** | 0 |
| `structured` | 14 | 0 | 0 |

`structured-prompt` needed the markdown-fence fallback on **11 of 14 cases** — its own
few-shot examples are fenced, so the model mimics them. Turning on `output_config.format`
eliminated it entirely. Structured outputs changed F1 by nothing and changed parse
reliability completely. A consumer without a fence fallback would break on 79% of
`structured-prompt` outputs while its F1 looked perfect.

Cost is not a design constraint here: $0.055 per case, about $8 for a full three-config
run over 50 cases.

---

## 8. What this harness cannot tell you

- Whether these numbers generalize past SEC filings. One genre.
- Whether `structured` beats `structured-prompt` on quality. The labels are too close to
  both.
- Anything with confidence at bucket level. `ambiguous` has 2 dev cases.
- Whether the judge is calibrated. **Judge validation was never run** — it needs 15
  hand-scored cases and the project ran out of time. The rubric is written and tested;
  the agreement number does not exist.
- Whether a deliberately regressed prompt is caught. The `regressed` config was built
  but never executed. The `baseline` → `structured-prompt` gap (0.38) does clear twice
  baseline's noise floor (0.28), so the harness demonstrably separates prompt quality
  above noise — but that is not the purpose-built test.

---

## 9. At customer scale

**Labeling is the budget line, not inference.** Inference for this entire project was
under $30. Labeling was the constraint that shaped every compromise in it, and the one
that broke first. Any customer eval plan that budgets GPU cost and not labeling hours
has mispriced the work.

**Someone must own the golden set.** Not "the team" — a person, with time allocated. The
inconsistency in §5 happened because labeling was squeezed at the end.

**Ground truth moves.** Diffing HPE's named competitors across three 10-Ks: 43% churn
one year, 24% the next. Juniper Networks left the list because **HPE acquired it**. No
prompt fixes that; only re-labeling does. Golden sets need a refresh cadence and a
change log.

**Measure your noise floor before you trust any delta.** There is no seed parameter.
Three replicates were not enough to estimate the floor stably — measuring baseline twice
gave 0.071 and 0.218 on identical data and config. Five is a better minimum, and the
floor should be published beside every result.

**Check the grader before blaming the model.** Seven times out of seven.

---

## Appendix: reproduce

```bash
python -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q
./.venv/bin/python -m src.cli grade --config structured-prompt --split dev
```

Runs offline from the committed response cache. No API key required.
