from __future__ import annotations

import re

# Phrases that, if present in a rationale, mean the model's own reasoning
# concluded there ISN'T a real contradiction -- so a verdict of "genuine" at
# the same time is self-contradictory. This is a real, observed failure mode
# (see dissonance/adjudicator/schema.py's field-order fix): putting
# `rationale` before `verdict` in the schema made the model reason before
# answering, which cut the rate sharply, but did not eliminate it -- some
# outputs still land the verdict field on a different conclusion than the
# rationale actually reached. This is a second, independent safety net, not
# a replacement for the schema fix.
_NOT_A_CONTRADICTION_PATTERNS = [
    # NOTE: each alternative inside a (?:...)? group must carry its OWN
    # trailing space -- `(?:genuine|real )?` only puts the space on the last
    # alternative, so "genuine" (no space) never matches "genuine " followed
    # by the next word. Got this wrong on the first attempt and it silently
    # dropped every multi-word match; caught by testing against a real
    # rationale the checker was supposed to catch and didn't.
    r"no (?:genuine |real |direct |true |evident |apparent |clear |obvious )?contradiction",
    r"not (?:a |truly |directly )?(?:genuine |real |direct |true |evident |apparent |clear |obvious )?contradict",
    r"does not contradict",
    r"doesn't contradict",
    r"compatible (?:perspectives|rather than contradictory|with (?:each other|one another))",
    r"consistent rather than contradictory",
    r"not (?:truly |directly )?conflicting",
    r"no (?:actual |real )?conflict",
    r"without (?:truly |directly |genuinely |really )?contradicting",
    r"rather than (?:a |the )?(?:direct |genuine |real |true |evident |apparent |clear |obvious )?"
    r"(?:contradicting|conflicting|contradiction|conflict)",
]
_NOT_A_CONTRADICTION_RE = re.compile("|".join(_NOT_A_CONTRADICTION_PATTERNS), re.IGNORECASE)


def rationale_contradicts_verdict(verdict: str, rationale: str) -> bool:
    """True if the rationale's own language undercuts a 'genuine' verdict --
    e.g. rationale says "no direct contradiction" but verdict says "genuine".
    Only checks the genuine-but-negated direction: that's the demonstrated,
    costly failure (a false positive genuine conflict). A rationale that
    argues FOR a contradiction while verdict says scope_difference is a much
    lower-stakes miss (plan.md's whole design already treats scope_difference
    conservatively), so it's not worth the false-positive risk of flagging it
    with the same keyword heuristic.

    This is a best-effort natural-language safety net, NOT a guarantee. FIVE
    separate rounds of testing against real adjudicator output each found a
    phrasing the previous version missed: "no contradiction" (bare), "not a
    genuine contradiction", "without contradicting each other", "no evident
    contradiction", "rather than a direct contradiction" (noun form -- the
    previous pattern only covered the gerund "contradicting"). At that point
    the pattern stopped being extended further; every remaining "genuine"
    verdict in the run that produced round 5's finding was corrected by
    manual read, not by chasing a sixth phrasing. Treat this function as
    narrowing the pool, not as proof: manually read every "genuine" verdict
    before trusting it, the way source-span hashes are mechanically verified
    elsewhere in this codebase but this is not."""
    if verdict != "genuine":
        return False
    return bool(_NOT_A_CONTRADICTION_RE.search(rationale))
