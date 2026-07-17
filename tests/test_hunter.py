from dissonance.hunter.embeddings import embedding_text


class TestEmbeddingText:
    def test_combines_assertion_subject_object(self):
        claim = {
            "assertion": "Few-shot prompting improves accuracy on GSM8K",
            "subject": "few-shot prompting",
            "object": "GSM8K accuracy",
        }

        text = embedding_text(claim)

        assert "Few-shot prompting improves accuracy on GSM8K" in text
        assert "few-shot prompting" in text
        assert "GSM8K accuracy" in text

    def test_handles_missing_subject_object(self):
        claim = {"assertion": "Some assertion", "subject": None, "object": None}

        text = embedding_text(claim)

        assert text == "Some assertion"
