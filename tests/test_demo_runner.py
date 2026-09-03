"""End to end through DemoState: one print, two feeds, two outcomes.

This is the claim the stream makes, so it gets a test that would fail if the
pairing, the per-feed books, or the shared judging were wrong.
"""
import pytest

from common.event import Event, Kind, Side, Source
from demo.runner import DZ, PUBLIC, DemoState
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


def test_dz_sizes_are_put_on_the_public_feed_axes_per_market():
    """The DZ side reports the underlying; a bot must see contracts, or its
    threshold means something different on every market."""
    from demo.runner import _rescale_dz

    btc = trade(Source.DZ_FEED, 1 * MS, 500_000, price=77756.0, size=0.0014)
    assert _rescale_dz(btc, 1e-4).size == pytest.approx(14.0)
    doge = trade(Source.DZ_FEED, 1 * MS, 500_000, price=0.0828, size=60_000.0)
    assert _rescale_dz(doge, 100.0).size == pytest.approx(600.0), \
        "the same 1e-4 on DOGE is what produced '6,000,000 contracts'"


def test_the_headline_fill_rates_come_from_paired_duels_only():
    """The number the stream quotes is per-duel, not per-bot: an intent one bot
    never had must not dilute either rate."""
    state = fresh_state()
    for event in dz_quote(100.0, 100.5, 0) + pub_quote(100.0, 100.5, 0):
        state.on_event(DZ if event.source is Source.DZ_FEED else PUBLIC, event)
    state.on_event(DZ, trade(Source.DZ_FEED, 1 * MS, 500_000))
    for event in dz_quote(100.0, 101.0, 3 * MS):
        state.on_event(DZ, event)
    state.on_event(PUBLIC, trade(Source.MARGIN_WS, 8 * MS, 500_000))
    state.settle_due()

    h2h = state.snapshot()["head_to_head"]
    assert h2h["n"] == 1
    assert h2h["dz_fill_rate"] == 100.0
    assert h2h["public_fill_rate"] == 0.0
    assert h2h["median_lead_ms"] == 7.0
