from common.event import Event, Kind, Side, Source
from race.match import match_trades


def _trade(t_ns, market="BTC", price=100.0, size=1.0, seq=None, source=Source.HL_WS):
    return (t_ns, Event(
        source=source, t_arrival_ns=t_ns, market=market, kind=Kind.TRADE,
        price=price, size=size, side=Side.BUY, seq=seq,
    ))


def test_exact_seq_match_yields_known_delta():
    a = [_trade(1_000_000, seq=42)]
    b = [_trade(1_003_000, seq=42, source=Source.DZ_FEED)]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.market == "BTC"
    assert p.price == 100.0
    assert p.size == 1.0
    assert p.seq == 42
    assert p.t_a_ns == 1_000_000
    assert p.t_b_ns == 1_003_000
    assert p.delta_ns == 3_000
    assert discarded_a == 0
    assert discarded_b == 0


def test_fallback_price_size_match_within_window_when_seq_missing():
    a = [_trade(1_000_000, price=50.5, size=2.0, seq=None)]
    b = [_trade(1_002_000, price=50.5, size=2.0, seq=None, source=Source.DZ_FEED)]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert len(pairs) == 1
    assert pairs[0].delta_ns == 2_000
    assert discarded_a == 0
    assert discarded_b == 0


def test_no_match_outside_window_is_discarded():
    a = [_trade(1_000_000, price=50.5, size=2.0, seq=None)]
    b = [_trade(10_000_000, price=50.5, size=2.0, seq=None, source=Source.DZ_FEED)]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=1_000_000)
    assert pairs == []
    assert discarded_a == 1
    assert discarded_b == 1


def test_no_match_when_price_differs_beyond_tolerance():
    a = [_trade(1_000_000, price=50.5, size=2.0, seq=None)]
    b = [_trade(1_001_000, price=50.6, size=2.0, seq=None, source=Source.DZ_FEED)]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert pairs == []
    assert discarded_a == 1
    assert discarded_b == 1


def test_each_event_matched_at_most_once():
    a = [_trade(1_000_000, seq=1), _trade(1_001_000, seq=2)]
    b = [
        _trade(1_000_500, seq=1, source=Source.DZ_FEED),
        _trade(1_001_500, seq=2, source=Source.DZ_FEED),
    ]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert len(pairs) == 2
    seqs = sorted(p.seq for p in pairs)
    assert seqs == [1, 2]
    assert discarded_a == 0
    assert discarded_b == 0


def test_nearest_in_time_fallback_picks_closest_candidate():
    # Two b candidates match a on price/size/market; nearest-in-time must win,
    # and the other must remain unmatched (discarded), never double-matched.
    a = [_trade(1_000_000, price=10.0, size=1.0, seq=None)]
    b = [
        _trade(1_004_000, price=10.0, size=1.0, seq=None, source=Source.DZ_FEED),
        _trade(1_000_800, price=10.0, size=1.0, seq=None, source=Source.DZ_FEED),
    ]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert len(pairs) == 1
    assert pairs[0].t_b_ns == 1_000_800
    assert discarded_a == 0
    assert discarded_b == 1


def test_non_trade_events_are_ignored():
    quote_a = (1_000_000, Event(
        source=Source.HL_WS, t_arrival_ns=1_000_000, market="BTC", kind=Kind.QUOTE,
        price=100.0, size=1.0, side=Side.BID, seq=None,
    ))
    a = [quote_a]
    b = []
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert pairs == []
    assert discarded_a == 0
    assert discarded_b == 0


def test_different_markets_do_not_match():
    a = [_trade(1_000_000, market="BTC", seq=42)]
    b = [_trade(1_000_500, market="ETH", seq=42, source=Source.DZ_FEED)]
    pairs, discarded_a, discarded_b = match_trades(a, b, window_ns=5_000_000)
    assert pairs == []
    assert discarded_a == 1
    assert discarded_b == 1
