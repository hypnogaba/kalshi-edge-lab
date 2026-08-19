"""Thin client for the public Kalshi prod REST (no auth required for reads)."""
import httpx

DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiRestClient:
    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 15.0):
        self._c = httpx.Client(base_url=base, timeout=timeout)

    def markets(self, series_ticker: str, status: str = "open", limit: int = 1000) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            params = {"series_ticker": series_ticker, "status": status, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            d = self._c.get("/markets", params=params).raise_for_status().json()
            out.extend(d.get("markets", []))
            cursor = d.get("cursor")
            if not cursor:
                return out

    def orderbook(self, ticker: str) -> dict:
        d = self._c.get(f"/markets/{ticker}/orderbook").raise_for_status().json()
        return d.get("orderbook", {})

    def trades(self, ticker: str, limit: int = 100) -> list[dict]:
        d = self._c.get("/markets/trades", params={"ticker": ticker, "limit": limit}).raise_for_status().json()
        return d.get("trades", [])

    def close(self) -> None:
        self._c.close()
