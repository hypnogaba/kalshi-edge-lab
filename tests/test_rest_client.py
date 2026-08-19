import httpx

from sources.kalshi_rest.client import KalshiRestClient


def _client(handler):
    transport = httpx.MockTransport(handler)
    c = KalshiRestClient()
    c._c = httpx.Client(base_url="https://x/trade-api/v2", transport=transport)
    return c


def test_markets_and_orderbook_and_trades():
    def handler(req):
        if req.url.path.endswith("/markets"):
            return httpx.Response(200, json={"markets": [{"ticker": "M1"}, {"ticker": "M2"}], "cursor": ""})
        if req.url.path.endswith("/orderbook"):
            return httpx.Response(200, json={"orderbook": {"yes": [[10, 5]], "no": None}})
        if req.url.path.endswith("/trades"):
            return httpx.Response(200, json={"trades": [{"trade_id": "t1"}]})
        return httpx.Response(404)
    c = _client(handler)
    assert [m["ticker"] for m in c.markets("KXBTC")] == ["M1", "M2"]
    assert c.orderbook("M1") == {"yes": [[10, 5]], "no": None}
    assert c.trades("M1") == [{"trade_id": "t1"}]
