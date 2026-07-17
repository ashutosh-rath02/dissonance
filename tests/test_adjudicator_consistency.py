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
