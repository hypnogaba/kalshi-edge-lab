import orjson

from common.event import Kind, Side, Source
from sources.kalshi_rest.decoder import decode


def test_trade_frame_decodes():
    frame = orjson.dumps({"kind": "trade", "ticker": "KXBTC-X-B68550", "data": {
        "trade_id": "abc", "ticker": "KXBTC-X-B68550", "taker_side": "yes",
        "yes_price_dollars": "0.0100", "no_price_dollars": "0.9900",
        "count_fp": "50.00", "created_time": "2026-08-19T15:37:39Z"}})
    events = decode(frame, t_arrival_ns=42)
    assert len(events) == 1
    e = events[0]
    assert e.source == Source.KALSHI_REST
    assert e.kind == Kind.TRADE and e.t_arrival_ns == 42
    assert e.market == "KXBTC-X-B68550" and e.price == 1 and e.size == 50 and e.side == Side.YES


def test_trade_no_side_uses_no_price():
    frame = orjson.dumps({"kind": "trade", "ticker": "M", "data": {
        "trade_id": "d", "ticker": "M", "taker_side": "no",
        "yes_price_dollars": "0.3000", "no_price_dollars": "0.7000",
        "count_fp": "3", "created_time": "t"}})
    e = decode(frame, 1)[0]
    assert e.side == Side.NO and e.price == 70


def test_orderbook_frame_expands_per_level():
    frame = orjson.dumps({"kind": "orderbook", "ticker": "M", "data": {
        "yes": [[10, 100], [11, 50]], "no": [[20, 30]]}})
    events = decode(frame, 1)
    assert len(events) == 3
    assert all(e.kind == Kind.BOOK_SNAPSHOT for e in events)
    assert {(e.price, e.size, e.side) for e in events if e.side == Side.YES} == {
        (10, 100, Side.YES), (11, 50, Side.YES)}


def test_empty_orderbook_yields_nothing():
    frame = orjson.dumps({"kind": "orderbook", "ticker": "M", "data": {"yes": None, "no": None}})
    assert decode(frame, 1) == []
