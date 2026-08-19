"""TDD for the DoubleZero Top-of-Book & Trades decoder (schema v3).

Builds raw wire frames by hand (frame header + packed app messages) per the
spec https://github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md
and asserts DzDecoder.decode(raw, t_arrival_ns) round-trips them into Events.
"""
import struct

from common.event import Kind, Side, Source
from sources.dz_feed.decoder import DzDecoder
from sources.dz_feed.registry import InstrumentRegistry

_MAGIC = 0x445A
_SCHEMA_VER = 3

# Frame header (24B): magic u16, schema_ver u8, channel_id u8, seq u64,
# send_ts_ns u64, msg_count u8, reset_count u8, frame_length u16.
_FRAME_HEADER = struct.Struct("<HBBQQBBH")

# App message header (4B): type u8, length u8, flags u16.
_MSG_HEADER = struct.Struct("<BBH")


def _msg_header(msg_type: int, length: int, flags: int = 0) -> bytes:
    return _MSG_HEADER.pack(msg_type, length, flags)


def _instrument_definition(instr_id: int, source_id: int, symbol: str,
                            price_exp: int, qty_exp: int) -> bytes:
    body = struct.pack(
        "<IH64s8s8sBbbBqQQQBBH",
        instr_id, source_id, symbol.encode("ascii"), b"", b"",
        0, price_exp, qty_exp, 0, 0, 0, 0, 0, 0, 0, 0,
    )
    return _msg_header(0x02, 130) + body


def _quote(instr_id: int, bid_price_raw: int, bid_qty_raw: int,
           ask_price_raw: int, ask_qty_raw: int, source_id: int = 1) -> bytes:
    # Trailing 4x is the spec's Reserved padding to 60 bytes (offset 56-59).
    body = struct.pack(
        "<IHBBQqQqQHH4x",
        instr_id, source_id, 0, 0, 0,
        bid_price_raw, bid_qty_raw, ask_price_raw, ask_qty_raw, 0, 0,
    )
    return _msg_header(0x03, 60) + body


def _trade(instr_id: int, aggressor: int, price_raw: int, qty_raw: int,
           trade_id: int, source_id: int = 1) -> bytes:
    body = struct.pack(
        "<IHBBQqQQQ",
        instr_id, source_id, aggressor, 0, 0,
        price_raw, qty_raw, trade_id, 0,
    )
    return _msg_header(0x04, 52) + body


def _frame(messages: list[bytes], seq: int = 1, channel_id: int = 1) -> bytes:
    body = b"".join(messages)
    header = _FRAME_HEADER.pack(
        _MAGIC, _SCHEMA_VER, channel_id, seq, 0, len(messages), 0, 24 + len(body))
    return header + body


def test_instrument_definition_then_quote_scales_prices():
    decoder = DzDecoder()
    frame = _frame([
        _instrument_definition(42, 1, "BTC", price_exp=-1, qty_exp=-3),
        _quote(42, bid_price_raw=681940, bid_qty_raw=500000,
               ask_price_raw=681950, ask_qty_raw=250000),
    ], seq=7)

    events = decoder.decode(frame, t_arrival_ns=123)

    assert len(events) == 2
    bid, ask = events
    assert bid.source == Source.DZ_FEED
    assert bid.t_arrival_ns == 123
    assert bid.market == "BTC"
    assert bid.kind == Kind.QUOTE
    assert bid.side == Side.BID
    assert bid.price == 68194.0
    assert bid.size == 500.0
    assert bid.seq == 7

    assert ask.side == Side.ASK
    assert ask.price == 68195.0
    assert ask.size == 250.0


def test_trade_buy_scales_price_and_size():
    decoder = DzDecoder()
    frame = _frame([
        _instrument_definition(7, 1, "ETH", price_exp=-2, qty_exp=-2),
        _trade(7, aggressor=1, price_raw=350000, qty_raw=150, trade_id=99),
    ], seq=3)

    events = decoder.decode(frame, t_arrival_ns=456)

    assert len(events) == 1
    trade = events[0]
    assert trade.kind == Kind.TRADE
    assert trade.side == Side.BUY
    assert trade.market == "ETH"
    assert trade.price == 3500.0
    assert trade.size == 1.5
    assert trade.seq == 99


def test_bad_magic_returns_no_events():
    decoder = DzDecoder()
    good = _frame([_trade(1, 1, 100, 1, 1)])
    bad = b"\x00\x00" + good[2:]
    assert decoder.decode(bad, t_arrival_ns=0) == []


def test_unknown_instrument_uses_raw_values_and_str_id():
    decoder = DzDecoder()
    frame = _frame([_trade(999, aggressor=2, price_raw=100, qty_raw=5, trade_id=1)])

    events = decoder.decode(frame, t_arrival_ns=0)

    assert len(events) == 1
    trade = events[0]
    assert trade.side == Side.SELL
    assert trade.market == "999"
    assert trade.price == 100
    assert trade.size == 5


def test_multi_message_frame_iterates_by_length():
    decoder = DzDecoder()
    frame = _frame([
        _instrument_definition(1, 1, "BTC", price_exp=0, qty_exp=0),
        _quote(1, bid_price_raw=100, bid_qty_raw=1, ask_price_raw=101, ask_qty_raw=2),
        _trade(1, aggressor=1, price_raw=101, qty_raw=1, trade_id=5),
    ])

    events = decoder.decode(frame, t_arrival_ns=0)

    assert len(events) == 3
    assert [e.kind for e in events] == [Kind.QUOTE, Kind.QUOTE, Kind.TRADE]


def test_registry_shared_across_decoder_instances():
    registry = InstrumentRegistry()
    registry.update(5, "SOL", price_exp=-1, qty_exp=0, source_id=1)
    decoder = DzDecoder(registry)
    frame = _frame([_trade(5, aggressor=1, price_raw=200, qty_raw=3, trade_id=1)])

    events = decoder.decode(frame, t_arrival_ns=0)

    assert events[0].market == "SOL"
    assert events[0].price == 20.0


def test_module_level_decode_matches_signature():
    from sources.dz_feed import decoder as dz_decoder
    frame = _frame([_trade(1, aggressor=1, price_raw=100, qty_raw=1, trade_id=1)])
    events = dz_decoder.decode(frame, 0)
    assert len(events) == 1
