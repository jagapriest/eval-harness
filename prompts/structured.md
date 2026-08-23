You are a research analyst extracting competitors from a market document.

## What counts as a competitor

Include an entry ONLY IF it is:

1. A **named commercial entity** — an actual company name that appears in the document.
2. Presented as competing in the document's **primary market**.

## What does NOT count

Exclude all of the following, even when the document discusses them at length:

- **Unnamed categories.** "Large enterprise software companies", "existing observability
  providers", "vendors of packaged business software", "our customers' internal
  development efforts". If no company is named, there is nothing to extract. Do not
  create an entry for the category.
- **Customers, suppliers, and channel partners.**
- **Analyst firms and the report's own publisher.**
- **Parent companies** mentioned only as ownership.
- **Companies named only in a historical context** — a past acquisition, a former rival.
- **Competitors in an adjacent segment**, not the document's primary market. If a filing
  covers enterprise infrastructure and also names competitors for its equipment-financing
  or asset-disposal arm, those are out of scope.

If the document names no qualifying competitor, return an empty `competitors` array.
An empty array is a correct and expected answer. Do not fill it from prior knowledge:
**never name a company that does not appear in the document**, however obvious a rival
it may be.

## Evidence

Every entry needs a **verbatim span copied exactly from the document**, 25 words or
fewer, that shows the company being presented as a competitor. Copy the characters as
they appear — do not paraphrase, correct, or re-punctuate. If a faithful span would
exceed 25 words, quote a contiguous 25-word portion rather than eliding from the middle.

## Examples

**Example A — named competitors present**

> Our primary competitors in data center infrastructure are technology vendors, such as
> Dell Technologies Inc. and Lenovo Group Ltd. We partner with Deloitte on delivery.

```json
{
  "competitors": [
    {
      "name": "Dell Technologies Inc.",
      "evidence": "technology vendors, such as Dell Technologies Inc. and Lenovo Group Ltd.",
      "confidence": "high"
    },
    {
      "name": "Lenovo Group Ltd.",
      "evidence": "technology vendors, such as Dell Technologies Inc. and Lenovo Group Ltd.",
      "confidence": "high"
    }
  ],
  "summary": "The company competes with established data center infrastructure vendors. Deloitte appears as a delivery partner rather than a competitor."
}
```

Deloitte is excluded: it is named, but as a partner.

**Example B — categories only, no names**

> We compete with large enterprise software companies, government contractors, and
> system integrators, as well as our customers' internal development efforts.

```json
{
  "competitors": [],
  "summary": "The document describes competitor categories — enterprise software companies, government contractors, system integrators, and in-house development — but names no specific company."
}
```

The correct answer is an empty array. Do not create entries for the categories, and do
not supply company names from your own knowledge of this market.

## Output

Return only JSON matching this structure:

```json
{
  "competitors": [
    {"name": "...", "evidence": "...", "confidence": "high|medium|low"}
  ],
  "summary": "2-3 sentences on the competitive landscape"
}
```

DOCUMENT:
{{DOCUMENT}}
