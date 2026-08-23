# Ralph Agent Instructions — eval-harness

You are an autonomous coding agent working on a Python LLM evaluation harness.

## Your Task

1. Read the PRD at `.claude/prd.json`
2. Read `.claude/progress.txt` (check the Codebase Patterns section first)
3. Read `writeup/spike-findings.md` — its measured results are load-bearing and several
   obvious-seeming design choices are already ruled out by them
4. Pick the next story per **Story Selection** below
5. Implement that single user story
6. Run quality checks: `./.venv/bin/python -m pytest -q` and `./.venv/bin/python -m compileall -q src scripts`
7. If checks pass, commit ALL changes: `feat: [Story ID] - [Story Title]`
8. Update `.claude/prd.json` to set `passes: true` for that story
9. Append to `.claude/progress.txt`

## Story Selection — READ THIS BEFORE PICKING

**Never pick a story with `"manual": true`.**

Three stories are owner-only gates: **US-001** (dataset labeling), **US-013** (judge
hand-scoring), **US-015** (findings.md). They are marked `manual: true` and
`blocking: true`.

You must not label cases, hand-score judge output, or write findings.md — not
partially, not as a draft, not as a "starting point" for the owner to edit. A
model-generated golden set, model-generated hand scores, or model-generated findings
would void the entire artifact this project exists to produce. That is the whole point
of the project, not a preference.

Selection rule:

1. Work through `implementationOrder` phases in order.
2. Within the current phase, pick the highest-priority story with `passes: false` and
   `manual: false`.
3. If every remaining story in the current phase is `manual: true`, **STOP** — see
   Stop Condition.
4. Never skip ahead past a `blocking: true` gate to reach later work.

## Dependencies

Phases 1–3 depend only on the **5 spike cases** in `data/cases/` as fixtures, not on
the 50-case dataset. Build against those. Do not wait for US-001 and do not invent
additional cases to test against — write fixtures inline in the test file when you
need more coverage.

## Quality Requirements

- All commits must pass `pytest`
- Do not commit broken code
- Keep changes focused and minimal
- **Harden what the spike built; do not rebuild it.** `src/schema.py`, `src/runner.py`,
  and both graders already work and are measured. Extend them.
- No new dependencies beyond `anthropic`, `pydantic`, `pyyaml`, `numpy`, `matplotlib`,
  `pytest`. If a story seems to need one, note it in progress.txt instead.
- Use `./.venv/bin/python`, not bare `python3`

## API Constraints (verified — do not "fix" these)

- `temperature` / `top_p` / `top_k` are **removed** on current models and return HTTP
  400. Judge variance comes from 3 plain calls, not sampling params.
- `budget_tokens` is removed. Use `output_config: {effort: ...}`.
- There is **no seed parameter**. Non-determinism is measured, not eliminated.
- Model IDs are exact strings, no date suffixes: `claude-opus-5`, `claude-haiku-4-5`.

## Cost Discipline

Tests must not call the live API. Use the committed cache in `results/cache/` or
fixtures. If a story genuinely needs a live call, mark the test
`@pytest.mark.live` and exclude it from the default run.

## Progress Report Format

APPEND to `.claude/progress.txt` (never replace):

```
## [Date/Time] - [Story ID]
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered
  - Gotchas encountered
  - Useful context
---
```

Add genuinely reusable patterns to a `## Codebase Patterns` section at the TOP of
progress.txt. Only general and reusable ones — not story-specific detail.

## Stop Condition

After completing a story, check what remains.

- If every remaining `passes: false` story is `manual: true`, reply with:
  `<promise>BLOCKED_ON_OWNER</promise>` and name which gate is next and what the owner
  needs to do. Do not attempt it.
- If ALL stories are `passes: true`, reply with `<promise>COMPLETE</promise>`.
- Otherwise end your response normally; the next iteration picks up the next story.

## Important

- One story per iteration
- Commit frequently
- No browser testing — this project has no UI
- No database migrations — this project has no database
- Spike-quality labels in `data/cases/` are provisional; never treat them as ground
  truth or "correct" them to make a test pass
