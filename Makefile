.PHONY: setup test lint check-auth discover capture
setup:
	uv sync
test:
	uv run pytest -q
lint:
	uv run ruff check .
check-auth:
	uv run python -m scripts.check_auth
discover:
	uv run python -m scripts.discover_markets
capture:
	uv run python -m sources.kalshi_ws.capture --market $(MARKET) --minutes $(MINUTES) --out $(OUT)
