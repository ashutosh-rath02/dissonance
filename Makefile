.PHONY: eval test lint migrate

eval:
	python -m evals.report

test:
	pytest -q

lint:
	ruff check dissonance tests web evals

migrate:
	python -m dissonance.graph.migrate
