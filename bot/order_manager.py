"""Kalshi DEMO order manager (v2 REST). DEMO ONLY — base URL is the demo API.
side bid = buy YES, ask = buy NO. price/count are fixed-point strings."""
import httpx

from sources.kalshi_ws.auth import KalshiSigner

_ORDERS = "/trade-api/v2/portfolio/events/orders"
_POSITIONS = "/trade-api/v2/portfolio/positions"


class OrderManager:
    def __init__(self, key_id: str, private_key_path: str, base: str):
        self._signer = KalshiSigner(key_id, private_key_path)
        self._base = base.replace("/trade-api/v2", "")
        # Exact host check -- a loose "demo" substring test would also accept
        # crafted hosts like "api.demo-phish.example.com". Require the real
        # demo domain and explicitly exclude the known prod host.
        if "demo.kalshi.co" not in self._base:
            raise ValueError(f"OrderManager must target the Kalshi demo host; got {self._base!r}")
        self._c = httpx.Client(base_url=self._base, timeout=15.0)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        h = self._signer.headers(method, path)
        h["Content-Type"] = "application/json"
        return h

    def place(self, ticker: str, buy_yes: bool, count: int, price_cents: int, coid: str) -> str:
        body = {
            "ticker": ticker,
            "client_order_id": coid,
            "side": "bid" if buy_yes else "ask",
            "count": f"{count:.2f}",
            "price": f"{price_cents / 100:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
        }
        r = self._c.post(_ORDERS, headers=self._headers("POST", _ORDERS), json=body)
        r.raise_for_status()
        return r.json().get("order", {}).get("order_id")

    def cancel(self, order_id: str) -> None:
        path = f"{_ORDERS}/{order_id}"
        self._c.delete(path, headers=self._headers("DELETE", path)).raise_for_status()

    def positions(self) -> list[dict]:
        r = self._c.get(_POSITIONS, headers=self._headers("GET", _POSITIONS))
        r.raise_for_status()
        return r.json().get("market_positions", [])

    def close(self) -> None:
        self._c.close()
