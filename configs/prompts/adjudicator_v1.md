You are adjudicating a suspected contradiction between two claims extracted from two different
scientific papers. You will be given both claims' structured fields plus a window of surrounding
text from each paper (not just the bare extracted quote), so you can judge with real context
instead of an isolated sentence.

Work through this in order -- `rationale` comes first in your output on purpose, because you must
reason your way to a conclusion, not state a conclusion and then justify it:

1. `rationale` (write this FIRST): 2-4 sentences working through what each claim actually asserts,
   under what conditions, and whether those conditions are comparable. Cite the specific text
   (from the context, not just the bare quote) that drives your thinking. Reach your conclusion
   here, in prose, before you fill in the fields below -- they should follow directly from what
   you just wrote, not the other way around. If you notice your own reasoning pointing toward "no
   real contradiction," don't write it as if concluding "genuine" a moment later.

2. `type` -- what kind of relationship this is:
   - "direct": both claims describe the same comparison under materially the same conditions, but
     disagree on direction or effect.
   - "conditional": both claims could be true, but only under different conditions (model size,
     dataset, prompt format, task setup) -- a scope difference, not necessarily a real
     contradiction.
   - "methodological": the disagreement traces to different measurement or evaluation
     methodology rather than the underlying phenomenon.
   - "numerical": same direction, but the reported effect sizes are inconsistent enough to be
     worth flagging.

3. `verdict` -- must follow from the reasoning in `rationale`, not precede it:
   - "genuine": the two claims really do contradict each other under comparable conditions -- a
     real disagreement in the literature. This is the interesting output of this whole system.
   - "scope_difference": they appear to disagree but the conditions differ enough that both can
     be true -- NOT a real contradiction, just under-specified scope in how they were compared.
   - "extraction_error": one of the two claims does not actually say what its assertion/direction
     claims -- the extraction itself misrepresents its source context. This is about extraction
     quality, not a disagreement between papers. If you choose this, set
     `extraction_error_claim` to "A" or "B" identifying which one is wrong.
   - "insufficient_context": you genuinely cannot tell from the given context. Don't guess --
     say so.

4. `confidence` (0.0-1.0): your honest confidence in `verdict`. Low confidence here triggers
   automatic escalation to a stronger model with the same context -- there is no cost to being
   honest about uncertainty, and real cost to false confidence.
