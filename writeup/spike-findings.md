# Spike findings — vertical slice, 5 cases

**Date:** 2026-08-22
**Config:** `baseline` — `claude-opus-5`, `effort: medium`, prompt-instructed JSON (no structured outputs)
**Dataset:** 5 SEC 10-K competition sections (~3,000 words each), spike-quality labels
**Total spend:** $1.12 (2 scored runs + a 3-replicate variance probe)

The spike existed to answer three questions before any dataset work. It answered all
three, and surfaced a fourth that matters more than the original three.

---

## 1. Is `evidence` verbatim-checkable? — Yes, 98%

**48 of 49 spans (98.0%)** were exact substring matches after whitespace/case/quote
normalization.

The prediction going in was ~70%, with paraphrase as the expected failure mode. That
was wrong. The model quotes accurately.

The single miss is not a model error either. The model wrote:

> `ITAD competitors are ERI, Ingram Micro, Sage Sustainable Electronics, and Sims Recycling Solutions`

The document reads:

> `Asset Disposition ("ITAD") competitors are ERI, Ingram Micro, ...`

It began the quote mid-phrase to stay under the 25-word cap. The span is faithful; it
is simply not contiguous. Similarity 0.96.

**Design consequences:**

- Verbatim-ness is **deterministic** and belongs in the set grader, not the judge. The
  original spec routed "evidence quality" to the LLM judge; that bundles two different
  things. Split them: *is it in the document* is a substring check, *does it support
  the claim* is judgment.
- Grade **exact** and **near-verbatim (≥0.95)** as separate outcomes. Collapsing them
  into pass/fail either manufactures failures or hides real ones.
- A word cap on quoted evidence induces mid-phrase elision. Either raise the cap or
  accept near-verbatim — don't do both a tight cap and a strict substring check.

### A grader can manufacture its own failures

First run scored 41/49 (83.6%) with the worst miss at 0.85 similarity. The cause was
**not the model** — it was EDGAR pagination artifacts (`10 Table of Contents`) injected
mid-sentence by the document pipeline. The model quoted the clean sentence; the grader
compared against the dirty one and called it a failure.

Stripping the artifact moved verbatim-ness from 83.6% → 98.0% with no change to the
model, the prompt, or the config. **A 14-point swing that was entirely the harness's
fault.** Worth stating plainly in the final writeup: before trusting any grader number,
check whether the grader is measuring the model or measuring itself.

---

## 2. What does a case cost? — $0.055, and cost is not a constraint

| Metric | Value |
|---|---|
| Cost per case | $0.055 |
| Projected: 50 cases × 3 configs | **$8.29** |
| Full project incl. 3× judge, with caching | well under $50 |
| Latency (median / max) | 7.7s / 25.1s |

Cost should not drive a single design decision on this project. Don't pick a smaller
model, fewer judge samples, or a smaller dataset to save money — none of it is
material. Pick them for methodological reasons or not at all.

---

## 3. Does the schema survive real documents? — Yes, with one caveat

- **5/5 outputs parsed as JSON.** Zero unparseable responses.
- **1/5 failed schema validation** — solely the >25-word evidence rule, and that was
  the same ITAD span from §1. One dirty document caused both failures.
- **Parse method varied run to run.** Run 1 recovered the largest case from a
  ```` ```json ```` fence; run 2 got it directly. Same prompt, same model.

That last point validates instrumenting *how* JSON was recovered rather than only
whether it was. The production `bank-intelligence` function does `JSON.parse()` with a
`jsonMatch[0]` regex fallback — this confirms that fallback is **load-bearing, and
intermittently so**, which is the worst kind of dependency to have undocumented.

---

## 4. The finding that matters most: the noise floor is 0.40

Three replicates of the **identical config** on the **identical dataset**:

| Replicate | macro-F1 |
|---|---|
| 1 | 0.720 |
| 2 | 0.920 |
| 3 | 0.520 |

**mean 0.720 · stdev 0.200 · spread 0.400**

There is no seed parameter in the Messages API. Output is non-deterministic by
construction, so the spec's "fix all seeds" is not achievable — what *is* achievable is
measuring the floor and refusing to call anything below it a regression.

**At n=5 this eval cannot detect anything.** A 0.40 swing is larger than any config
delta worth measuring. This is empirical support for the ≥30-case minimum, and it is
the number the deliberately-regressed-prompt test must be gated on.

### The variance is structural, not uniform

| Case | F1 per replicate | Spread | Extractions |
|---|---|---|---|
| clean_002 (HPE, 35 competitors) | 1.0, 1.0, 1.0 | **0.00** | 35, 35, 35 |
| ambiguous_002 (empty) | 1.0, 1.0, 1.0 | **0.00** | 0, 0, 0 |
| ambiguous_001 (Snowflake) | 0.6, 0.6, 0.6 | **0.00** | 7, 7, 7 |
| adversarial_001 (Palantir) | 0.0, 1.0, 0.0 | **1.00** | 7, 0, 6 |
| clean_001 (Dell, empty) | 1.0, 1.0, 0.0 | **1.00** | 0, 0, 3 |

The hardest recall case is **perfectly reproducible** — 35 of 35 competitors, three
times running. All the variance lives in cases where the correct answer is "extract
nothing" and the prompt never says whether *categories* count as competitors.

The model oscillates between two defensible readings of an underspecified instruction.
That is not model instability; it is **specification ambiguity, and it is measurable.**
Prediction worth testing: the `structured` config's explicit exclusion criteria should
collapse most of this variance. If it does, that is the headline result — prompt
precision bought reproducibility, not just accuracy.

---

## 5. Zero hallucination — the predicted failure mode did not appear

Across 15 case-runs and 49 extractions: **0 hits on `must_not_include`, 0 fabricated
company names.**

Three of five documents name no competitors at all and instead describe categories
("branded and generic competitors", "the internal software development efforts of our
potential customers"). Going in, the expectation was that this would bait
training-knowledge leakage — Databricks for Snowflake, Oracle and SAP for Salesforce.
It never happened once.

When the model over-extracted, it emitted **categories, honestly self-labeled**:

```
"Large enterprise software companies (unnamed)"
"Existing observability solution providers (unnamed)"
"Customers' internal software development efforts (in-house build)"
```

These score as false positives under a spec requiring "a named commercial entity" —
correctly so — but they are a different failure than hallucination, and they call for a
different fix (tighten the prompt) than the one `must_not_include` was designed to
catch (constrain the model's priors).

---

## 6. The labels were the weakest link

On the HPE case, first-pass hand-labeling recorded **30** competitors. The model found
**35**, and all five extras were verifiably named in the source:

- **Nile**, **Meter** — "networking-as-a-service vendors such as Nile and Meter"
- **IBM Global Financing**, **Dell Financial Services**, **Cisco Capital** — "captive
  financing companies, such as ..."

A **17% label error rate**, all omissions, all in the reader's blind spot rather than
the model's. Before correction the case scored P=0.86; after, P=1.00. The eval was
measuring the labeler.

Two consequences:

1. **Model-assisted pre-labeling is a correctness improvement, not just a speed-up.**
   It must still be disclosed, and a cold-labeled subset is still needed to measure
   anchoring — but the naive assumption that hand labels are ground truth and model
   output is the thing under test did not survive five cases.
2. **Recall was 1.00 on every case in every replicate.** All measured error was
   precision, and most of it was label error or prompt underspecification. On this
   task the interesting metric is precision; recall is close to solved.

---

## Implications for the PRD

**Change:**

1. **The `clean` bucket cannot come from 10-Ks.** Three of five name zero companies.
   10-Ks are an excellent cheap source for `empty` / `adversarial` / `ambiguous`;
   `clean` needs analyst comparisons or trade press.
2. **Re-weight the buckets.** Variance is concentrated in `empty` / `adversarial`, so
   those need *more* cases than `clean`, not fewer. The current 15 clean / 5 empty
   split is backwards relative to where the measurement is unstable.
3. **Drop "fix all seeds."** Replace with: measure the noise floor, publish it, and
   gate the regression test on it.
4. **Split evidence grading** — deterministic verbatim-ness in the set grader,
   quality in the judge. Grade exact and near-verbatim separately.
5. **Add document-artifact normalization** as a first-class pipeline step, with the
   83.6% → 98.0% swing as the justification.

**Keep unchanged:** grader tiering, judge-only-on-prose, bucket breakouts,
`must_not_include` as a first-class field, the regressed-prompt acceptance test,
committed cache, hard stop at 50 cases.

**Open question for the owner:** multi-segment filers. HPE's document names competitors
for enterprise IT infrastructure *and* for ITAD and captive financing — adjacencies,
not the "primary market" the spec scopes to. Including them added 9 of 35 expected
names on that case. This will recur on most large filers and needs a ruling before
labeling begins, because it moves recall on every affected case.

---

## Caveat

**n = 5. These labels are spike-quality**, produced in one pass to unblock the harness
build, and one of them has already been corrected. Every number here is directional.
The 0.40 noise floor in particular is itself measured at n=5 and should be re-measured
on the real dev split before anything is gated on it.
