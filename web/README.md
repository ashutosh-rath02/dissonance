# Web UI

Two sections in one FastAPI app, same retro amber-phosphor terminal theme, server-rendered
(Jinja2, no JS framework, no build step):

- **`web/app.py`** -- the Week 3 golden-set labeling tool (internal, plan.md §5.1).
- **`web/living_review.py`** -- the Week 5 living review (public-facing output, plan.md §8).

```bash
./.venv/Scripts/python.exe -m uvicorn web.app:app --reload
```

Then open http://127.0.0.1:8000/.

## Claim review (`/`, `/papers/{paper_id}`) -- internal labeling tool

- **Dashboard** (`/`): every ingested paper, extraction status, claim/label counts, and an
  `[ EXPORT GOLDEN SET ]` button.
- **Paper review** (`/papers/{paper_id}`): every extracted claim next to its source quote. The
  quote isn't stored in the DB (plan.md §3.2 stores only `char_start`/`char_end` + a hash) -- this
  page re-fetches the paper and slices the span live, then shows `HASH OK` / `HASH MISMATCH`. That
  mismatch check is the citation-faithfulness verification plan.md §5.2 describes, made visible.
- Label each claim `[ CORRECT ]` / `[ INCORRECT ]` / `[ UNCERTAIN ]` with optional notes.
- `[ EXPORT GOLDEN SET ]` writes every `correct`-labeled claim to `evals/golden/claims.json` in
  the exact production Claim schema -- that's what the Week 3 eval harness scores extraction
  against.

## Living review (`/review`) -- the public-facing output

- **Contradiction table** (`/review`): every adjudicated conflict, filterable by verdict
  (genuine / scope_difference / insufficient_context), with corpus stats up top. This is the
  "hero view" plan.md §8 describes.
- **Conflict detail** (`/review/conflicts/{conflict_id}`): both claims side by side, each with its
  quote re-verified live against the source paper (same `HASH OK` mechanism as claim review),
  full structured fields (subject/object/direction/effect_size/conditions), and the adjudicator's
  rationale.
- **Escalation queue** (`/review/escalated`): conflicts the adjudicator couldn't resolve on its
  own (`status='escalated_to_human'`) -- either genuinely `insufficient_context`, or a
  self-contradictory "genuine" verdict the consistency checker
  (`dissonance/adjudicator/consistency.py`) caught and routed here instead of trusting. A human
  reads the rationale and both quotes, then clicks `[ GENUINE CONTRADICTION ]` or
  `[ SCOPE DIFFERENCE ]` to resolve it -- the override is appended to the rationale (not a
  replacement), so the adjudicator's original reasoning stays visible alongside the final call.

As of the last full run: 1553 conflicts adjudicated, 0 confirmed genuine, 1552
`scope_difference`, 1 resolved via the escalation queue above. See README's Honesty rule section
for why 0 genuine is a real, hard-won number, not a placeholder.

## Notes

- Plain HTML forms, full-page redirects after every action -- no JS required, works with any
  browser, no build step.
- Paper full-text is cached in-process per run (`_TEXT_CACHE` in `app.py` and separately in
  `living_review.py`) to avoid re-fetching arXiv on every page view. Restart the server if a
  paper's HTML changed upstream and you need a fresh fetch.
