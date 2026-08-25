# My eval harness reported a perfect score. Every single API call had failed.

I spent a weekend building an evaluation harness for an LLM extraction task — the kind
of thing you build when you want to know whether changing a prompt made things better or
just different.

Partway through, it printed the most beautiful result I'd seen all project. Three
identical runs, three identical scores. Zero variance. Perfect reproducibility.

I was drafting the writeup in my head when I noticed the cost line said **$0.00**.

Every API call had returned a 400. My credit balance had run out. Every response body was
empty — and an empty extraction happens to score 1.00 on documents that name no
competitors and 0.00 on documents that do. Averaged across my test set, that produced a
rock-stable macro-F1 of exactly 0.500, three runs running.

**Determinism from total failure looks exactly like excellence.**

That was the sixth of seven times my own harness produced a number that looked like a
model failure and turned out to be my failure. Those seven are the actual finding. The
scores were the least interesting output of the project.

---

## The setup

The task: pull named competitors out of a market document, with a verbatim quote
supporting each one. Source material was real SEC 10-K "Competition" sections — public,
free, and structurally perfect, because a filing names its rivals right alongside its
auditors, customers, and suppliers. Precision has to work for.

48 labeled cases in five buckets. Clean filings that name competitors outright.
Ambiguous ones where a company is partner *and* rival. Adversarial ones stuffed with
non-competitor names. Empty ones that name nobody. Long ones to test context handling.

Three graders: two deterministic, one LLM-as-judge. Total inference cost for the whole
project, including every re-run: under $30.

---

## The seven times the harness lied to me

**1. Page breaks cost 14 points of accuracy.** SEC filings inject "10 Table of Contents"
mid-sentence. My grader compared the model's clean quote against the dirty source and
called it a hallucination. Stripping the artifact moved measured accuracy from 83.6% to
98.0% — with no change to the model, the prompt, or anything else.

**2. Name normalization split one company into two.** `International Business Machines
Corporation (IBM)` and `IBM` scored as different entities. Same for `Broadcom/VMware` and
`Broadcom`. When I diffed one company's competitor list across three years of filings,
this alone inflated the apparent churn by 7 points.

**3. My hand labels missed 17% of the answers.** On one filing I recorded 30 competitors.
The model found 35 — and all five extras were verifiably in the text. I'd skimmed past
them. Before I fixed my labels, that case scored 86% precision. After, 100%. The eval was
measuring me.

**4. A test broke on a line wrap.** I asserted a phrase appeared in my grading rubric. It
did — with a newline in the middle. Same class of whitespace bug as #1, which I had
already fixed once.

**5. A path helper crashed completed runs.** Writing results outside the repo threw an
exception *after* the expensive work had finished.

**6. The billing outage above.**

**7. A config parameter that returns HTTP 400.** I'd set a reasoning-effort parameter on a
model that doesn't accept it. That configuration would have failed on every single case —
silently, if I hadn't hit the same wall elsewhere first.

Seven for seven. Not one was the model.

---

## The one that would have made me publish a wrong conclusion

Two configurations, identical model, identical data:

- **Prompt with explicit exclusion criteria, plain JSON output:** needed a markdown-fence
  fallback to parse **11 of 14 responses**
- **Same prompt, with structured outputs enabled:** **14 of 14 parsed directly**

F1 was *identical* between them. If I'd only looked at quality metrics, I'd have concluded
structured outputs added nothing.

What they actually did was eliminate a parse failure mode entirely. The strong prompt
contains few-shot examples wrapped in code fences — so the model copied that formatting.
A downstream consumer without a fence-stripping fallback would break on **79%** of those
responses while the quality dashboard showed everything green.

That's the kind of thing an eval only catches if you instrument *how* the output was
recovered, not just whether it was valid.

---

## What I got wrong about what would go wrong

I expected hallucination to dominate. Three of my documents name no competitors at all —
they describe categories, like "large enterprise software companies and system
integrators." Textbook bait for a model to fill in the famous names from memory.

Across 49 extractions: **zero fabricated companies.** Not one.

When the model over-extracted, it emitted the *categories* — honestly labeled `(unnamed)`.
That's a real failure under a spec requiring named entities, but it's a completely
different failure, and it needs a completely different fix. I'd built my precision
tripwire for the wrong thing.

---

## The number nobody publishes

There is no seed parameter. LLM output is non-deterministic by construction, so before any
comparison means anything you have to know how much a configuration varies *against
itself*.

I ran the same config on the same data five times. Macro-F1: 0.598, 0.523, 0.309, 0.594,
0.447.

**A spread of 0.288 with nothing changed at all.** Any "improvement" smaller than that is
indistinguishable from re-running the thing you already had.

Two consequences I didn't anticipate:

Three replicates isn't enough to *estimate* that spread. I measured the same config twice
and got 0.071, then 0.218.

And an unstable baseline makes your eval blind. The weak prompt's spread was 0.288; the
strong prompt's was 0.004. Fixing the prompt didn't just raise the score — it made the
harness *capable of detecting a regression at all*.

---

## What I'd tell someone doing this for real

**Labeling is the budget line. Not inference.** Inference was under $30. Labeling was the
constraint that shaped every compromise in the project and the thing that broke first —
under time pressure my own accept rate swung from 100% on one filing to 0% on a nearly
identical one, twenty rejections in twenty-two seconds. I rejected Intel and Nvidia as
competitors *on AMD's own annual report*. Any eval plan that budgets compute and not
labeling hours has mispriced the work.

**Somebody has to own the golden set.** A person, with time allocated. Not "the team."

**Ground truth moves.** Diffing one company's named competitors across three annual
filings: 43% turnover one year, 24% the next. One competitor disappeared from the list
because **the company acquired it.** No prompt fixes that. Only re-labeling does. Golden
sets need a refresh cadence and a change log, same as any other production asset.

**Check the grader before you blame the model.** Seven times out of seven.

---

## The uncomfortable part

I ran out of time. When I did, I normalized my inconsistent labels using a rule that
leans on machine signals — and that rule draws on the same output the strong
configurations produce. So they're partly being graded against their own answers.

The final F1 of 0.99 is not a real result, and I've said so at the top of the repo, in the
README, and in the split file. The original human labels are preserved beside the
normalized ones so anyone can see exactly what changed and how much it mattered.

I'd rather publish that caveat loudly than publish 0.99 quietly. An eval that flatters
itself is worse than no eval — it's the false assurance the whole practice exists to
prevent.

Which is, I suppose, the eighth thing the harness taught me: the failure mode you're most
likely to miss is the one that makes your results look good.

---

*Code and full writeup: github.com/jagapriest/eval-harness — clones and runs offline
from a committed response cache, no API key needed.*
