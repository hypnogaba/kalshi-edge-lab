import orjson

from common.event import Kind, Side, Source
from sources.hl_ws.decoder import decode


def test_trade_message_decodes_to_trade_event():
    raw = orjson.dumps({
        "channel": "trades",
        "data": [{
            "coin": "BTC", "side": "B", "px": "68194.0", "sz": "0.04743",
            "time": 1787161931931, "tid": 1046810456480897,
            "hash": "0xabc", "users": ["0x1", "0x2"],
        }],
    })
    events = decode(raw, t_arrival_ns=555)
    assert len(events) == 1
    e = events[0]
    assert e.source == Source.HL_WS and e.kind == Kind.TRADE and e.t_arrival_ns == 555
    assert e.market == "BTC"
    assert e.price == 68194.0 and isinstance(e.price, float)
    assert e.size == 0.04743 and isinstance(e.size, float)
    assert e.side == Side.BUY
    assert e.seq == 1046810456480897


def test_trade_sell_side_maps_to_sell():
    raw = orjson.dumps({
        "channel": "trades",
        "data": [{
            "coin": "ETH", "side": "A", "px": "3000.5", "sz": "1.2",
            "time": 1787161931931, "tid": 42,
        }],
    })
    events = decode(raw, t_arrival_ns=1)
    assert len(events) == 1
    assert events[0].side == Side.SELL


def test_trade_message_with_multiple_trades_yields_multiple_events():
    raw = orjson.dumps({
        "channel": "trades",
        "data": [
            {"coin": "BTC", "side": "B", "px": "1.0", "sz": "1.0", "time": 1, "tid": 1},
            {"coin": "BTC", "side": "A", "px": "2.0", "sz": "2.0", "time": 2, "tid": 2},
        ],
    })
    events = decode(raw, t_arrival_ns=1)
    assert len(events) == 2


def test_bbo_message_decodes_to_two_quote_events():
    raw = orjson.dumps({
        "channel": "bbo",
        "data": {
            "coin": "BTC", "time": 1787161938748,
            "bbo": [
                {"px": "68186.0", "sz": "2.43653", "n": 8},
                {"px": "68187.0", "sz": "14.6915", "n": 38},
            ],
        },
    })
    events = decode(raw, t_arrival_ns=999)
    assert len(events) == 2
    bid = next(e for e in events if e.side == Side.BID)
    ask = next(e for e in events if e.side == Side.ASK)
    assert bid.kind == Kind.QUOTE and bid.source == Source.HL_WS and bid.t_arrival_ns == 999
    assert bid.market == "BTC"
    assert bid.price == 68186.0 and bid.size == 2.43653 and bid.seq == 1787161938748
    assert ask.price == 68187.0 and ask.size == 14.6915 and ask.seq == 1787161938748


def test_bbo_message_with_null_bid_yields_only_ask_event():
    raw = orjson.dumps({
        "channel": "bbo",
        "data": {
            "coin": "BTC", "time": 123,
            "bbo": [None, {"px": "10.0", "sz": "1.0", "n": 1}],
        },
    })
    events = decode(raw, t_arrival_ns=1)
    assert len(events) == 1
    assert events[0].side == Side.ASK


def test_bbo_message_with_null_ask_yields_only_bid_event():
    raw = orjson.dumps({
        "channel": "bbo",
        "data": {
            "coin": "BTC", "time": 123,
            "bbo": [{"px": "10.0", "sz": "1.0", "n": 1}, None],
        },
    })
    events = decode(raw, t_arrival_ns=1)
    assert len(events) == 1
    assert events[0].side == Side.BID


def test_subscription_response_yields_no_events():
    raw = orjson.dumps({"channel": "subscriptionResponse", "data": {"method": "subscribe"}})
    assert decode(raw, t_arrival_ns=1) == []
