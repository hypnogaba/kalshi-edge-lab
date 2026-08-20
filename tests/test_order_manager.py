import httpx
import orjson

from bot.order_manager import OrderManager


class _FakeSigner:
    key_id = "k"

    def headers(self, method, path, now_ms=None):
        return {"KALSHI-ACCESS-KEY": "k", "KALSHI-ACCESS-SIGNATURE": "s", "KALSHI-ACCESS-TIMESTAMP": "1"}


def _om(handler):
    # Build without running __init__ (which would try to load a real private key file) —
    # inject a fake signer and a MockTransport client directly, as the test needs no real network/key.
    om = OrderManager.__new__(OrderManager)
    om._signer = _FakeSigner()
    om._base = "https://d.demo.kalshi.co"
    om._c = httpx.Client(base_url="https://d.demo.kalshi.co", transport=httpx.MockTransport(handler))
    return om


def test_place_buy_yes_builds_v2_body():
    captured = {}

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/portfolio/events/orders"):
            captured.update(orjson.loads(req.content))
            return httpx.Response(201, json={"order": {"order_id": "o1"}})
        return httpx.Response(404)

    om = _om(handler)
    oid = om.place(ticker="KXBTCD-X-T68000", buy_yes=True, count=2, price_cents=56, coid="c1")
    assert oid == "o1"
    assert captured["ticker"] == "KXBTCD-X-T68000"
    assert captured["side"] == "bid"
    assert captured["count"] == "2.00"
    assert captured["price"] == "0.5600"
    assert captured["client_order_id"] == "c1"
    assert captured["time_in_force"] == "good_till_canceled"


def test_place_buy_no_uses_ask():
    def handler(req):
        return httpx.Response(201, json={"order": {"order_id": "o2"}})

    om = _om(handler)
    assert om.place("M", buy_yes=False, count=1, price_cents=30, coid="c2") == "o2"


def test_cancel_hits_delete_path():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["path"] = req.url.path
        return httpx.Response(200, json={})

    om = _om(handler)
    om.cancel("o1")
    assert seen["method"] == "DELETE" and seen["path"].endswith("/portfolio/events/orders/o1")
