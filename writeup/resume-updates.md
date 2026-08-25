# Resume updates — eval harness

Target: **Delvon Jones Resume — Anthropic Manager, Applied AI Architecture**

The current resume has **zero** LLM-evaluation coverage. The only match for "evaluat" is
"$10M+ evaluations," which reads as sales cycles. Every Applied AI req names evaluation
as a core responsibility, so this was the one listed requirement with no supporting
evidence. These four edits close it.

Ordered by impact. Edit 1 alone does most of the work.

---

## 1. SIGNATURE ACHIEVEMENTS — add one bullet

Place it **directly after** the "Five production LLM applications shipped" bullet, so the
build evidence and the measurement evidence sit together.

> – **Designed and published an open-source LLM evaluation harness** — 48-case golden
> dataset built from SEC filings, deterministic set-grading separated from LLM-as-judge
> prose grading, bucket-level reporting with bootstrap confidence intervals, and a
> **measured run-to-run noise floor** that regression detection is gated on. Surfaced
> seven defects in its own measurement pipeline that each presented as a model failure.
> Total inference cost under $30.

**Why this wording:** "gated on a measured noise floor" is the phrase that signals you've
actually run evals rather than read about them — most people never measure how much a
config varies against itself. "Seven defects in its own measurement pipeline" is the
credibility line: it says you distrust your own instruments, which is the whole job.

---

## 2. Summary paragraph — one clause

**Current:**
> But I don't just advise — I build. Five production LLM applications shipped, including
> agentic systems on the Claude API with hybrid RAG and privacy-partitioned local
> inference.

**Replace with:**
> But I don't just advise — I build, and I measure what I build. Five production LLM
> applications shipped, including agentic systems on the Claude API with hybrid RAG and
> privacy-partitioned local inference — plus a published evaluation harness that scores
> those systems and catches prompt regressions before they ship.

---

## 3. Keyword line — add one term

**Current:**
> Pre-Sales Leadership | Production LLM Applications | Claude API & MCP | Agentic
> Architecture & Hybrid RAG | C-Suite Technical Advisory | $100M+ Pursuit Governance |
> Regulated Industries (FSI) | Team Building & Enablement

**Add after "Agentic Architecture & Hybrid RAG":**
> | LLM Evaluation & Regression Testing

---

## 4. TECHNICAL → AI/LLM line — extend

**Current ends:**
> ...Prompt and context engineering · NVIDIA NIM · Langflow · n8n

**Replace that tail with:**
> ...Prompt and context engineering · **LLM evaluation** (golden datasets, deterministic
> and LLM-as-judge grading, noise-floor measurement, bootstrap confidence intervals,
> regression gating) · NVIDIA NIM · Langflow · n8n

---

## Optional: link the repo

If the resume carries a projects or links line, add:

> **eval-harness** — github.com/jagapriest/eval-harness · clones and runs offline from a
> committed response cache; no API key required to verify it works.

That last clause matters more than it looks. Most portfolio repos can't be checked
without setup. This one can be verified in about thirty seconds, and saying so invites
the check.

---

## Claims to avoid

Do not put these on the resume. They will not survive a follow-up question.

| Don't say | Why |
|---|---|
| "Validated the LLM judge against human scores" | **Never ran.** The rubric is written and tested; the agreement number does not exist. |
| Any specific F1 as an achievement | The final 0.99 is inflated by partly machine-normalized labels. Publishing it invites the one question you can't answer well. |
| "50-case dataset" | It is 48. |
| "Caught a deliberately regressed prompt" | The purpose-built regressed config never executed — the budget ran out. The harness *does* separate a weaker prompt from a stronger one above noise, which is what the bullet claims. |

---

## If asked about it in an interview

The strongest answer is not the harness. It's this:

> "Seven times, a number that looked like a model failure was a defect in my own grader.
> The worst one: a billing outage made every API call fail, every response came back
> empty, and empty responses happened to score perfectly on part of my dataset. The
> harness reported flawless determinism — three identical runs, zero variance — from
> total failure. I nearly wrote it up as the headline finding. Now both code paths abort
> instead of averaging, with a regression test."

Then the honest limitation, unprompted:

> "I also ran out of time on labeling and normalized my golden set with a rule that uses
> machine signals, which makes part of the result circular. I said so at the top of the
> repo rather than burying it, and I kept the original human labels beside the normalized
> ones so anyone can see what changed."

Volunteering that is worth more than the project. It demonstrates the exact instinct
evaluation work requires — and an interviewer who finds it themselves after you've
claimed 0.99 reaches a very different conclusion.
