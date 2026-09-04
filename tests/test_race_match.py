"""The offline matcher, held to the id spaces the two feeds really use."""
import uuid

from common.event import Event, Kind, Side, Source
from race.match import match_trades

TICK = 0.5
_ticks = {"BTC": TICK, "ETH": TICK}


def tick_of(market: str) -> float | None:
    return _ticks.get(market)


def _trade(t_ns, market="BTC", price=100.0, size=1.0, exch_ts_ns=None,
           source=Source.MARGIN_WS, seq=None):
    return (t_ns, Event(
        source=source, t_arrival_ns=t_ns, market=market, kind=Kind.TRADE,
        price=price, size=size, side=Side.BUY, seq=seq,
        exch_ts_ns=t_ns if exch_ts_ns is None else exch_ts_ns,
    ))


def _public(t_ns, **kw):
    """The public side stamps a UUID trade id, which does not fit in Event.seq."""
    return _trade(t_ns, source=Source.MARGIN_WS, seq=None, **kw)


def _dz(t_ns, **kw):
    """The DZ side stamps the venue's u64 trade id in seq."""
    seq = kw.pop("seq", uuid.uuid4().int >> 64)
    return _trade(t_ns, source=Source.DZ_FEED, seq=seq, **kw)


def test_the_same_trade_on_both_feeds_matches_on_the_venues_own_fields():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, exch_ts_ns=exch)]
    b = [_dz(1_003_000, exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.market == "BTC" and p.price == 100.0 and p.size == 1.0
    assert p.exch_ts_ns == exch
    assert p.delta_ns == 3_000
    assert (da, db) == (0, 0)


def test_unrelated_trades_that_share_a_seq_must_not_match():
    """The regression this file used to encode instead of catch.

    On the public side `seq` is a per-subscription message counter, so seq=42 is
    simply the 42nd message on the socket. On the DZ side it is the venue's u64
    trade id. Two trades sharing that number have nothing to do with each other:
    different market, different price, different venue stamp, 40 seconds apart.
    Matching them was the old pass 1, and it had no time window at all.
    """
    a = [_public(1_000_000, market="BTC", price=100.0, exch_ts_ns=1_000_000)]
    b = [_dz(41_000_000_000, market="ETH", price=7.5,
             exch_ts_ns=41_000_000_000, seq=42)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (1, 1)


def test_no_match_outside_the_window_is_discarded():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, exch_ts_ns=exch)]
    b = [_dz(10_000_000, exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=1_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (1, 1)


def test_a_price_more_than_a_tick_apart_is_a_different_trade():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, price=100.0, exch_ts_ns=exch)]
    b = [_dz(1_001_000, price=100.0 + TICK, exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (1, 1)


def test_prices_that_differ_only_by_float_noise_still_match():
    """The two feeds reach the price by different arithmetic: one multiplies a
    raw i64 by 1e-8, the other divides a decimal string by the contract size.
    Quantising by the tick is what makes those two land on one key."""
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, price=100.0, exch_ts_ns=exch)]
    b = [_dz(1_001_000, price=100.00000000001, exch_ts_ns=exch)]
    pairs, _da, _db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert len(pairs) == 1


def test_a_cheap_market_keeps_its_price_in_the_key():
    """Rounding the price to whole dollars, which is what this used to do,
    turned every DOGE and KSHIB price into 0, so two different trades in the
    same millisecond with the same size collapsed onto one key."""
    _ticks["DOGE"] = 1e-6
    try:
        exch = 1_000_000_000_000_000
        a = [_public(1_000_000, market="DOGE", price=0.089196, exch_ts_ns=exch)]
        b = [_dz(1_001_000, market="DOGE", price=0.089201, exch_ts_ns=exch)]
        pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
        assert pairs == [], "prices five ticks apart are not the same trade"
        assert (da, db) == (1, 1)
    finally:
        del _ticks["DOGE"]


def test_each_trade_is_used_at_most_once():
    exch1, exch2 = 1_000_000_000_000_000, 1_000_000_000_001_000
    a = [_public(1_000_000, price=100.0, exch_ts_ns=exch1),
         _public(1_001_000, price=101.0, exch_ts_ns=exch2)]
    b = [_dz(1_000_500, price=100.0, exch_ts_ns=exch1),
         _dz(1_001_500, price=101.0, exch_ts_ns=exch2)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert len(pairs) == 2
    assert {p.price for p in pairs} == {100.0, 101.0}
    assert (da, db) == (0, 0)


def test_two_candidates_on_one_key_go_to_the_nearest_in_time():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, exch_ts_ns=exch)]
    b = [_dz(1_004_000, exch_ts_ns=exch), _dz(1_000_800, exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert len(pairs) == 1
    assert pairs[0].t_b_ns == 1_000_800
    assert (da, db) == (0, 1)


def test_a_market_with_no_reference_data_is_skipped_not_guessed():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, market="SOL", exch_ts_ns=exch)]
    b = [_dz(1_001_000, market="SOL", exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (1, 1)


def test_non_trade_events_are_ignored():
    quote = (1_000_000, Event(
        source=Source.MARGIN_WS, t_arrival_ns=1_000_000, market="BTC",
        kind=Kind.QUOTE, price=100.0, size=1.0, side=Side.BID,
        exch_ts_ns=1_000_000))
    pairs, da, db = match_trades([quote], [], window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (0, 0)


def test_different_markets_do_not_match():
    exch = 1_000_000_000_000_000
    a = [_public(1_000_000, market="BTC", exch_ts_ns=exch)]
    b = [_dz(1_000_500, market="ETH", exch_ts_ns=exch)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (1, 1)


def test_a_trade_without_a_venue_stamp_cannot_be_keyed():
    a = [(1_000_000, Event(source=Source.MARGIN_WS, t_arrival_ns=1_000_000,
                           market="BTC", kind=Kind.TRADE, price=100.0, size=1.0))]
    b = [_dz(1_001_000, exch_ts_ns=1_000_000)]
    pairs, da, db = match_trades(a, b, window_ns=5_000_000, tick_of=tick_of)
    assert pairs == []
    assert (da, db) == (0, 1)
