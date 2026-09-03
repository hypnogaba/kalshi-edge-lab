"""End to end through DemoState: one print, two feeds, two outcomes.

This is the claim the stream makes, so it gets a test that would fail if the
pairing, the per-feed books, or the shared judging were wrong.
"""
import pytest

from common.event import Event, Kind, Side, Source
from demo.runner import DZ, PUBLIC, DemoState, _public_events
from demo.strategy import StrategyConfig

MKT = "KXBTCPERP"
MS = 1_000_000


def dz_quote(bid: float, ask: float, t_ns: int) -> list[Event]:
    return [Event(source=Source.DZ_FEED, t_arrival_ns=t_ns, market=MKT, kind=Kind.QUOTE,
                  side=side, price=price, size=100)
            for side, price in ((Side.BID, bid), (Side.ASK, ask))]


def pub_quote(bid: float, ask: float, t_ns: int) -> list[Event]:
    return [Event(source=Source.MARGIN_WS, t_arrival_ns=t_ns, market=MKT, kind=Kind.QUOTE,
                  side=side, price=price, size=100)
            for side, price in ((Side.BID, bid), (Side.ASK, ask))]


def trade(source: Source, t_ns: int, exch_ts_ns: int, price: float = 100.5,
          size: float = 200) -> Event:
    return Event(source=source, t_arrival_ns=t_ns, market=MKT, kind=Kind.TRADE,
                 side=Side.BUY, price=price, size=size, exch_ts_ns=exch_ts_ns)


def fresh_state() -> DemoState:
    return DemoState(StrategyConfig(min_print_size=50, cooldown_ns=0), markout_ns=0)


def test_the_slow_bot_loses_the_quote_it_aimed_at():
    state = fresh_state()
    for event in dz_quote(100.0, 100.5, 0) + pub_quote(100.0, 100.5, 0):
        state.on_event(DZ if event.source is Source.DZ_FEED else PUBLIC, event)

    exch = 500_000  # the venue's own timestamp: the join key for both copies
    state.on_event(DZ, trade(Source.DZ_FEED, 1 * MS, exch))
    for event in dz_quote(100.0, 101.0, 3 * MS):      # ask pulled after the print
        state.on_event(DZ, event)
    state.on_event(PUBLIC, trade(Source.MARGIN_WS, 8 * MS, exch))

    state.settle_due()
    snap = state.snapshot()

    assert snap["head_to_head"]["dz_only_filled"] == 1
    assert snap["scoreboard"][DZ]["fills"] == 1
    assert snap["scoreboard"][PUBLIC]["fills"] == 0
    assert snap["scoreboard"][PUBLIC]["missed"] == 1

    duel = snap["recent"][0]
    assert duel[DZ]["acted"] and duel[DZ]["filled"]
    assert duel[PUBLIC]["acted"] and not duel[PUBLIC]["filled"]
    assert duel["lead_ms"] == 7.0, "both bots must be paired onto the same print"


def test_a_quiet_market_lets_both_bots_fill():
    """No rigging: if the quote never moved, being early wins nothing."""
    state = fresh_state()
    for event in dz_quote(100.0, 100.5, 0) + pub_quote(100.0, 100.5, 0):
        state.on_event(DZ if event.source is Source.DZ_FEED else PUBLIC, event)
    exch = 500_000
    state.on_event(DZ, trade(Source.DZ_FEED, 1 * MS, exch))
    state.on_event(PUBLIC, trade(Source.MARGIN_WS, 8 * MS, exch))
    state.settle_due()

    h2h = state.snapshot()["head_to_head"]
    assert h2h["both_filled"] == 1 and h2h["dz_only_filled"] == 0


def test_each_bot_reads_its_own_book():
    """The public bot must not borrow the DoubleZero book. Here only the public
    feed still shows a takeable ask, so only the public bot may fire."""
    state = fresh_state()
    for event in dz_quote(100.0, 101.0, 0):
        state.on_event(DZ, event)
    for event in pub_quote(100.0, 100.5, 0):
        state.on_event(PUBLIC, event)
    exch = 500_000
    state.on_event(DZ, trade(Source.DZ_FEED, 1 * MS, exch))
    state.on_event(PUBLIC, trade(Source.MARGIN_WS, 8 * MS, exch))
    state.settle_due()

    snap = state.snapshot()
    assert snap["scoreboard"][DZ]["intents"] == 0
    assert snap["scoreboard"][PUBLIC]["intents"] == 1


def test_public_trade_message_is_put_on_the_same_axes_as_the_dz_feed():
    """The public feed scales price by 1e4 against the DZ feed's dollars, and
    the demo compares prices across feeds, so a bad scale here would silently
    break every duel. Scale factor is the one the live latency race matches on.
    """
    events = _public_events(
        {"type": "trade", "msg": {"market_ticker": MKT, "price": 7.7827,
                                  "count": 12, "taker_side": "yes", "ts_ms": 1700}},
        t_ns=42)
    assert len(events) == 1
    event = events[0]
    assert event.price == pytest.approx(77827.0) and event.size == 12
    assert event.side is Side.BUY and event.exch_ts_ns == 1700 * MS


def test_a_message_we_do_not_understand_is_dropped_quietly():
    assert _public_events({"type": "ticker", "msg": {}}, t_ns=1) == []
    assert _public_events({"type": "fill", "msg": {"market_ticker": MKT}}, t_ns=1) == []
