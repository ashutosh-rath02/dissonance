You are extracting typed, verifiable claims from an LLM-evaluation research paper for a
contradiction-detection system. Only extract claims that assert a *quantitative or directional
relationship* between a method/intervention and a measured outcome (e.g. "few-shot prompting
increases GSM8K accuracy", "temperature scaling reduces judge disagreement").

Rules:
- Extract only claims explicitly stated in the given text (abstract, results, or conclusion). Do
  not infer claims the authors didn't state.
- `quote` must be an EXACT, VERBATIM substring of the input text that supports the claim -- copy
  it character-for-character, including punctuation. Do not paraphrase or summarize into `quote`.
  This is mechanically checked (Python substring search) against the exact text you were given; a
  quote that doesn't appear verbatim invalidates the claim.
  - NEVER use "..." or any other elision inside `quote` to skip or join text -- that will never
    match the source and always fails validation. If the full supporting sentence is long, quote a
    SHORT, CONTIGUOUS span (as little as one clause) that is still self-contained enough to support
    the claim, rather than trying to compress a long span with an ellipsis.
  - Before writing each `quote`, re-read it against the source text in your head character by
    character. If you are not certain it is an exact substring, pick a shorter, safer span instead.
- `subject` is the method/intervention/factor being varied (e.g. "few-shot prompting",
  "chain-of-thought", "judge model choice"). `object` is what's measured (e.g. "GSM8K accuracy",
  "inter-annotator agreement").
- `conditions` captures what makes the claim scope-limited: model class/size, dataset/population,
  and any other qualifiers (temperature, shot count, prompt format). This is what lets a later
  adjudicator tell a genuine contradiction from two claims that are both true under different
  conditions -- be specific here, don't leave it empty if the paper specifies conditions.
- `evidence_strength`: "primary_result" if it's this paper's own experimental finding,
  "secondary_result" if it's a secondary/ablation finding, "cited_claim" if the paper is reporting
  someone else's finding (not its own).
- `confidence` (0.0-1.0) is YOUR self-assessed confidence that this claim is accurately extracted
  and the quote genuinely supports it. Be honest -- low confidence on ambiguous claims is more
  useful than false confidence.
- If the text contains no extractable claims, return an empty `claims` list. Do not force claims
  that aren't there.

Extract at most 10 claims from the given text, prioritizing the paper's primary results.
