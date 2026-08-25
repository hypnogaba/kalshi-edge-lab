.PHONY: setup test lint selfcheck check-auth capture
setup:
	uv sync
test:
	uv run pytest -q
lint:
	uv run ruff check .
selfcheck:
	uv run python -m scripts.run_race --selfcheck
check-auth:
	uv run python -m scripts.check_auth
capture:
	uv run python -m sources.kalshi_ws.capture --market $(MARKET) --minutes $(MINUTES) --out $(OUT)
