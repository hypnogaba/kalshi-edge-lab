"""Pinned to real message shapes captured from the live public socket.

Every literal below is a real payload observed on
wss://external-api-margin-ws.kalshi.com, not an invention from the docs.
"""
import pytest

from common.event import Kind, Side
from demo.public_feed import PublicFeed

MKT = "KXBTCPERP"


def snapshot(bids, asks, market=MKT):
    return {"type": "orderbook_snapshot", "msg": {"market_ticker": market,
                                                  "bid": bids, "ask": asks}}


def delta(price, size, side, market=MKT):
    return {"type": "orderbook_delta", "msg": {"market_ticker": market, "price": price,
                                               "delta": size, "side": side,
                                               "ts_ms": 1788427882746}}


def test_a_bid_taker_is_a_buy():
    """taker_side='bid' printed at or above the ask on every one of 14 live
    trades and never at or below the bid. Reading it as a sell would invert the
    strategy and quietly make the whole demo meaningless."""
    feed = PublicFeed()
    events = feed.on_message(
        {"type": "trade", "msg": {"market_ticker": MKT, "price": "7.7720",
                                  "count": "13.00", "taker_side": "bid",
                                  "ts_ms": 1788427884151}}, t_ns=42)
    assert len(events) == 1
    trade = events[0]
    assert trade.side is Side.BUY
    assert trade.price == pytest.approx(77720.0), "prices arrive 1e4 below dollars"
    assert trade.size == 13.0
    assert trade.exch_ts_ns == 1788427884151 * 1_000_000


def test_an_ask_taker_is_a_sell():
    feed = PublicFeed()
    trade = feed.on_message(
        {"type": "trade", "msg": {"market_ticker": MKT, "price": "7.7715",
                                  "count": "2.00", "taker_side": "ask",
                                  "ts_ms": 1788427884151}}, t_ns=42)[0]
    assert trade.side is Side.SELL


def test_snapshot_gives_the_top_of_a_deep_book():
    """The live snapshot carries dozens of levels far from the market; only the
    top of each side is a quote."""
    feed = PublicFeed()
    events = feed.on_message(snapshot(
        bids=[["5.1000", "3.00"], ["5.4301", "18100.00"], ["7.7715", "3.00"]],
        asks=[["7.7720", "334.00"], ["7.9000", "12.00"]]), t_ns=1)
    quotes = {event.side: event for event in events}
    assert quotes[Side.BID].price == pytest.approx(77715.0)
    assert quotes[Side.ASK].price == pytest.approx(77720.0)
    assert quotes[Side.BID].size == 3.0
    assert all(event.kind is Kind.QUOTE for event in events)


def test_a_delta_that_empties_the_best_level_moves_the_top():
    feed = PublicFeed()
    feed.on_message(snapshot(bids=[["7.7715", "3.00"], ["7.7700", "9.00"]],
                             asks=[["7.7720", "334.00"]]), t_ns=1)
    events = feed.on_message(delta("7.7715", "-3.00", "bid"), t_ns=2)
    bid = next(event for event in events if event.side is Side.BID)
    assert bid.price == pytest.approx(77700.0), "best bid must fall to the next level"


def test_deep_book_churn_emits_nothing():
    """22330 deltas a minute arrive on three markets. A bot only ever acts on
    the top, so a delta that leaves the top alone must not produce a quote."""
    feed = PublicFeed()
    feed.on_message(snapshot(bids=[["7.7715", "3.00"]], asks=[["7.7720", "334.00"]]),
                    t_ns=1)
    assert feed.on_message(delta("5.4301", "18100.00", "bid"), t_ns=2) == []


def test_a_delta_can_add_a_new_best():
    feed = PublicFeed()
    feed.on_message(snapshot(bids=[["7.7715", "3.00"]], asks=[["7.7720", "334.00"]]),
                    t_ns=1)
    events = feed.on_message(delta("7.7718", "5.00", "bid"), t_ns=2)
    bid = next(event for event in events if event.side is Side.BID)
    assert bid.price == pytest.approx(77718.0) and bid.size == 5.0


def test_book_state_survives_a_one_sided_market():
    feed = PublicFeed()
    feed.on_message(snapshot(bids=[], asks=[["7.7720", "334.00"]]), t_ns=1)
    assert feed.best(MKT) == (None, pytest.approx(77720.0))


def test_junk_is_dropped_quietly():
    feed = PublicFeed()
    assert feed.on_message({"type": "subscribed", "msg": {"channel": "trade"}}, 1) == []
    assert feed.on_message({"type": "trade", "msg": {"market_ticker": MKT}}, 1) == []
    assert feed.on_message({"type": "orderbook_delta",
                            "msg": {"market_ticker": MKT, "side": "middle"}}, 1) == []


def test_two_markets_do_not_share_a_book():
    feed = PublicFeed()
    feed.on_message(snapshot(bids=[["7.7715", "3.00"]], asks=[["7.7720", "1.00"]]), 1)
    feed.on_message(snapshot(bids=[["2.3990", "8.00"]], asks=[["2.3997", "6.00"]],
                             market="KXETHPERP"), 2)
    assert feed.best(MKT)[0] == pytest.approx(77715.0)
    assert feed.best("KXETHPERP")[0] == pytest.approx(23990.0)
