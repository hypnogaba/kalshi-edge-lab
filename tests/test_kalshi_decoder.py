"""The perps/margin WS decoder, held to frames recorded off the live socket.

Every frame in tests/data/margin_trades.jsonl came off
wss://external-api-margin-ws.kalshi.com. The previous version of this file
built its own frames in the shape the docs described, which is why it stayed
green while the decoder read `yes_price` from a feed that sends `price`.
"""
from pathlib import Path

from common.event import Kind, Side, Source
from sources.kalshi_ws.decoder import decode

FIX = Path(__file__).parent / "data" / "margin_trades.jsonl"


def _frames() -> list[bytes]:
    return [line.encode() for line in FIX.read_text().splitlines() if line.strip()]


def _trades() -> list:
    out = []
    for raw in _frames():
        out.extend(decode(raw, t_arrival_ns=1))
    return out


def test_every_recorded_trade_decodes_with_all_four_join_fields():
    """Price, size and the venue stamp are what the race joins on. A decoder
    that returns None for any of them makes the match silently skip the trade,
    which is exactly how the old one failed: `yes_price` is absent here, so
    price was None on every single frame."""
    trades = _trades()
    assert len(trades) >= 40
    for e in trades:
        assert e.kind is Kind.TRADE
        assert e.source is Source.MARGIN_WS
        assert e.market.endswith("PERP")
        assert isinstance(e.price, float) and e.price > 0
        assert isinstance(e.size, float) and e.size > 0
        assert e.exch_ts_ns and e.exch_ts_ns > 1_700_000_000_000_000_000
        assert e.side in (Side.BUY, Side.SELL)


def test_numbers_arrive_as_strings_and_come_back_as_numbers():
    raw = b'{"type":"trade","sid":1,"seq":9,"msg":{"trade_id":"0721c72a-1","market_ticker":"KXBTCPERP","price":"8.0961","count":"617.00","taker_side":"ask","ts_ms":1788502115168}}'
    e = decode(raw, t_arrival_ns=555)[0]
    assert e.price == 8.0961 and e.size == 617.0
    assert e.t_arrival_ns == 555
    assert e.exch_ts_ns == 1788502115168 * 1_000_000


def test_taker_side_is_bid_ask_not_yes_no():
    """bid = the aggressor lifted the offer = a BUY. Reading it the other way
    round inverts every side the demo reports."""
    bid = decode(b'{"type":"trade","msg":{"market_ticker":"KXETHPERP","price":"2.5033","count":"3.00","taker_side":"bid","ts_ms":1788457749964}}', 1)[0]
    ask = decode(b'{"type":"trade","msg":{"market_ticker":"KXETHPERP","price":"2.5033","count":"3.00","taker_side":"ask","ts_ms":1788457749964}}', 1)[0]
    assert bid.side is Side.BUY
    assert ask.side is Side.SELL


def test_price_is_left_on_the_venue_axis_dollars_per_contract():
    """$8.0961 per BTC contract is $80,961 per BTC. Converting needs the
    market's contract size, which only the DoubleZero reference data carries,
    so the decoder must NOT guess a scale here."""
    e = decode(b'{"type":"trade","msg":{"market_ticker":"KXBTCPERP","price":"8.0961","count":"1.00","taker_side":"bid","ts_ms":1788502115168}}', 1)[0]
    assert e.price == 8.0961


def test_seq_is_not_used_as_a_trade_id():
    """The frame's `seq` counts messages on the subscription, not trades. The
    DoubleZero side's `seq` is the venue's u64 trade id. Carrying this one into
    Event.seq invites a matcher to join two unrelated id spaces."""
    frames = [f for f in _frames() if b'"type":"trade"' in f]
    assert any(b'"seq":1' in f for f in frames)  # the counter really is in the data
    for raw in frames:
        assert decode(raw, 1)[0].seq is None


def test_control_frames_and_other_channels_yield_nothing():
    assert decode(b'{"type":"subscribed","id":1,"msg":{"channel":"trade","sid":1}}', 1) == []
    assert decode(b'{"type":"orderbook_delta","msg":{"market_ticker":"KXBTCPERP","price":"8.09","delta":-2,"side":"bid"}}', 1) == []


def test_a_malformed_trade_is_dropped_not_half_decoded():
    """Half a trade is worse than none: it would key on a price of zero."""
    assert decode(b'{"type":"trade","msg":{"market_ticker":"KXBTCPERP","count":"1.00","ts_ms":1}}', 1) == []
    assert decode(b'{"type":"trade","msg":{"market_ticker":"KXBTCPERP","price":"x","count":"1.00","ts_ms":1}}', 1) == []
    assert decode(b'{"type":"trade","msg":{"price":"8.09","count":"1.00","ts_ms":1}}', 1) == []


def test_the_recorded_capture_carries_both_sides_and_several_markets():
    """Guards the fixture itself: a capture of one market on one side would let
    a side- or market-specific bug through."""
    trades = _trades()
    assert {t.side for t in trades} == {Side.BUY, Side.SELL}
    assert len({t.market for t in trades}) >= 2
