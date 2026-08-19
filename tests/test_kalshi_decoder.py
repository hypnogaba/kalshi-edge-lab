from pathlib import Path

import orjson

from common.event import Kind, Side, Source
from sources.kalshi_ws.decoder import decode

FIX = Path(__file__).parent / "data" / "kalshi_samples.jsonl"


def _load():
    return [line for line in FIX.read_text().splitlines() if line.strip()]


def test_control_messages_yield_nothing():
    ctrl = orjson.dumps({"type": "subscribed", "id": 1, "msg": {"channel": "trade", "sid": 2}}).decode()
    assert decode(ctrl.encode(), t_arrival_ns=1) == []


def test_trade_decodes_to_single_trade_event():
    raw = orjson.dumps({
        "type": "trade", "sid": 12,
        "msg": {"market_ticker": "KXBTC", "yes_price": 52, "count": 3, "taker_side": "yes", "ts": 1700},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=555)
    assert len(events) == 1
    e = events[0]
    assert e.source == Source.KALSHI_WS and e.kind == Kind.TRADE and e.t_arrival_ns == 555
    assert e.market == "KXBTC" and e.price == 52 and e.size == 3 and e.side == Side.YES


def test_delta_decodes_to_single_book_delta():
    raw = orjson.dumps({
        "type": "orderbook_delta", "sid": 12, "seq": 7,
        "msg": {"market_ticker": "KXBTC", "price": 40, "delta": -2, "side": "no"},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=1)
    assert len(events) == 1
    e = events[0]
    assert e.kind == Kind.BOOK_DELTA and e.price == 40 and e.size == -2 and e.side == Side.NO and e.seq == 7


def test_snapshot_expands_to_one_event_per_level():
    raw = orjson.dumps({
        "type": "orderbook_snapshot", "sid": 12, "seq": 1,
        "msg": {"market_ticker": "KXBTC", "yes": [[10, 100], [11, 50]], "no": [[20, 30]]},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=1)
    assert len(events) == 3
    assert all(e.kind == Kind.BOOK_SNAPSHOT and e.seq == 1 for e in events)
    yes = {(e.price, e.size) for e in events if e.side == Side.YES}
    no = {(e.price, e.size) for e in events if e.side == Side.NO}
    assert yes == {(10, 100), (11, 50)} and no == {(20, 30)}


def test_empty_snapshot_yields_no_events():
    # Real demo snapshot: empty book, no yes/no arrays.
    raw = orjson.dumps({
        "type": "orderbook_snapshot", "sid": 1, "seq": 1,
        "msg": {"market_ticker": "KXBTCD-26AUG2017-T73749.99", "market_id": "x"},
    }).decode()
    assert decode(raw.encode(), t_arrival_ns=1) == []


def test_every_fixture_line_decodes_without_error():
    for line in _load():
        decode(line.encode(), t_arrival_ns=1)  # must not raise
