.PHONY: lint test check

lint:
	uv run python scripts/lint.py

test:
	PYTHONPATH=.:tools uv run --with pytest --with pytest-cov pytest -q tests \
		--cov=harness --cov=game_state --cov=arc_repl --cov=arc_repl_cli \
		--cov-fail-under=80

check: lint test
