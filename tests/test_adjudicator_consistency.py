from dissonance.adjudicator.consistency import rationale_contradicts_verdict


class TestRationaleContradictsVerdict:
    def test_genuine_with_negating_rationale_is_flagged(self):
        rationale = "These are compatible perspectives rather than contradictory."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_no_direct_contradiction_phrase_is_flagged(self):
        rationale = "There is no direct contradiction as both claims indicate the same trend."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_does_not_contradict_is_flagged(self):
        rationale = "Claim A and claim B do not contradict each other under these conditions."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_bare_no_contradiction_is_flagged(self):
        # Regression test: the original regex required an adjective between
        # "no" and "contradiction" (e.g. "no direct contradiction") and
        # missed this bare phrasing entirely -- a real rationale from a real
        # adjudicator run used exactly this wording and slipped through.
        rationale = "There is no contradiction, only agreement from slightly different angles."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_not_a_genuine_contradiction_is_flagged(self):
        # Regression test: the original regex's (?:genuine|real|direct|true )?
        # group only put the trailing space on the LAST alternative, so
        # "genuine" (no space) never matched "genuine contradiction" -- this
        # exact phrase, from a real rationale, silently passed the buggy
        # checker despite being an unambiguous self-contradiction.
        rationale = "Hence, this is not a genuine contradiction but a shared view about updating benchmarks."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_without_contradicting_is_flagged(self):
        # Regression test: third real phrasing found during verification,
        # after the first two fixes -- "without contradicting each other".
        rationale = "Both describe similar phenomena without contradicting each other; they reinforce ongoing challenges."
        assert rationale_contradicts_verdict("genuine", rationale) is True

    def test_genuine_with_consistent_reasoning_is_not_flagged(self):
        rationale = (
            "Claim A reports worse performance while Claim B reports better performance "
            "under comparable conditions, so this is a genuine contradiction."
        )
        assert rationale_contradicts_verdict("genuine", rationale) is False

    def test_scope_difference_is_never_flagged_regardless_of_rationale(self):
        # Only the genuine-but-negated direction is checked (see module docstring).
        rationale = "This is a genuine, direct contradiction with no explaining scope difference."
        assert rationale_contradicts_verdict("scope_difference", rationale) is False

    def test_insufficient_context_is_never_flagged(self):
        assert rationale_contradicts_verdict("insufficient_context", "no contradiction found") is False
