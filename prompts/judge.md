You are evaluating the quality of an extraction system's **prose output**.

You are NOT evaluating which companies were extracted. That is graded separately by
exact rules. Do not comment on whether the competitor list is right, complete, or
missing anyone. Judge only the writing.

## What you are scoring

The `summary` field, and the *quality* of the evidence spans as support — not whether
those spans appear verbatim in the document, which is also checked by rule.

## Axes

Score each axis 1–5. Score them independently: a summary can be perfectly faithful and
badly written.

### Faithfulness — is every claim traceable to the document?

- **5** — Every claim is directly supported by the document. No added figures, causes, dates, or market characterizations that the document does not contain.
- **4** — Fully supported, but one characterization is slightly stronger than the document warrants (e.g. "dominant" where the document says "significant").
- **3** — Mostly supported, with one claim that requires outside knowledge or a modest inferential leap the document does not license.
- **2** — Contains a claim contradicted by the document, or two or more unsupported assertions.
- **1** — Substantially invented: named companies, figures, or events that do not appear in the document at all.

*Worked example, score 2:* the document names competitor categories only, and the
summary asserts "the company competes primarily with Oracle and SAP." Those names are
not in the document — the model supplied them from prior knowledge.

*Worked example, score 4:* the document says the market is "highly competitive and
rapidly evolving"; the summary says "intensely contested." Supported, mildly amplified.

### Relevance — does it address the competitive landscape?

- **5** — Entirely about the competitive landscape: who competes, on what basis, how the market is structured.
- **4** — Focused, with one sentence of tangential context.
- **3** — Roughly half is about something else — product features, financial results, strategy unrelated to competition.
- **2** — Mostly off-topic; competition is mentioned but not characterized.
- **1** — Does not address competition at all.

*Worked example, score 3:* two sentences describe the competitive set, then a third
summarizes the company's revenue mix, which the question did not ask about.

### Concision — is it 2–3 sentences carrying real information?

- **5** — 2–3 sentences, every clause carrying content.
- **4** — Correct length, with one redundant or filler clause.
- **3** — Slightly over or under length (1 sentence, or 4), or noticeably padded.
- **2** — Substantially over length, or repeats the same point in different words.
- **1** — A single vague sentence, or a paragraph restating the document at length.

*Worked example, score 2:* five sentences, two of which restate "the market is
competitive" using different adjectives.

## An important case

If the document names no competitors and the summary correctly says so, that is a
**good** summary. Score it on its own merits — a faithful, relevant, concise statement
that the document describes categories rather than naming companies deserves 5s. Do not
penalize it for being short or for having nothing to list.

## Output

Reason first, then score. The reasoning must come before the numbers — quote the
specific phrase driving each score.

Return only JSON:

```json
{
  "reasoning": "Your assessment, referencing specific phrases from the summary.",
  "faithfulness": 1-5,
  "relevance": 1-5,
  "concision": 1-5
}
```

---

## SOURCE DOCUMENT

{{DOCUMENT}}

---

## SUMMARY UNDER EVALUATION

{{SUMMARY}}

## EVIDENCE SPANS CITED

{{EVIDENCE}}
