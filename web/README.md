# Claim review UI

The Week 3 golden-set labeling tool (plan.md §5.1). Retro amber-phosphor terminal theme, server-rendered (FastAPI + Jinja2, no JS framework, no build step).

```bash
./.venv/Scripts/python.exe -m uvicorn web.app:app --reload
```

Then open http://127.0.0.1:8000/.

## What it does

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

## Notes

- Plain HTML forms, full-page redirects after every label -- no JS required, works with any
  browser, no build step.
- Paper full-text is cached in-process per run (`_TEXT_CACHE` in `app.py`) to avoid re-fetching
  arXiv on every page view while reviewing the same paper's claims. Restart the server if a
  paper's HTML changed upstream and you need a fresh fetch.
