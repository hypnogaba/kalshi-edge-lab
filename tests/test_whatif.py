from common.event import Event, Kind, Side, Source
from race.whatif import build_opportunities, whatif_stats


def _trade(t_ns, market="BTC", price=50.0, size=1.0, seq=None, source=Source.KALSHI_WS):
    return (t_ns, Event(
        source=source, t_arrival_ns=t_ns, market=market, kind=Kind.TRADE,
        price=price, size=size, side=Side.BUY, seq=seq,
    ))


def test_whatif_stats_empty_yields_n_zero_only():
    assert whatif_stats([]) == {"n": 0}


def test_whatif_stats_hand_computable_aggregate():
    # edge_adv = public_price - edge_price: +2.0, -1.0, +3.0, 0.0
    opportunities = [
        {"delta_ns": 3_000_000, "edge_price": 50.0, "public_price": 52.0},
        {"delta_ns": 5_000_000, "edge_price": 48.0, "public_price": 47.0},
        {"delta_ns": 2_000_000, "edge_price": 30.0, "public_price": 33.0},
        {"delta_ns": 4_000_000, "edge_price": 60.0, "public_price": 60.0},
    ]
    stats = whatif_stats(opportunities)
    assert stats["n"] == 4
    # delta_ms sorted [2,3,4,5] -> median (3+4)/2
    assert stats["median_delta_ms"] == 3.5
    # mean(2,-1,3,0) = 1.0
    assert stats["avg_edge_cents"] == 1.0
    # sum(2,-1,3,0)/100 * 1 contract = 0.04
    assert stats["total_edge_dollars"] == 0.04
    # 2 of 4 advantages strictly positive
    assert stats["win_rate"] == 50.0


def test_whatif_stats_contract_count_scales_total_dollars_only():
    opportunities = [
        {"delta_ns": 3_000_000, "edge_price": 50.0, "public_price": 52.0},
        {"delta_ns": 5_000_000, "edge_price": 48.0, "public_price": 47.0},
        {"delta_ns": 2_000_000, "edge_price": 30.0, "public_price": 33.0},
        {"delta_ns": 4_000_000, "edge_price": 60.0, "public_price": 60.0},
    ]
    stats = whatif_stats(opportunities, contract_count=250)
    assert stats["total_edge_dollars"] == 10.0
    assert stats["n"] == 4
    assert stats["win_rate"] == 50.0


def test_whatif_stats_all_negative_advantage_yields_zero_win_rate():
    opportunities = [
        {"delta_ns": 1_000_000, "edge_price": 50.0, "public_price": 49.0},
        {"delta_ns": 1_000_000, "edge_price": 50.0, "public_price": 48.0},
    ]
    stats = whatif_stats(opportunities)
    assert stats["win_rate"] == 0.0
    assert stats["avg_edge_cents"] == -1.5


def test_build_opportunities_uses_next_public_trade_after_catch_up():
    # DZ sees the trade at t=1_000_000 (price 50.0). Its matched public copy
    # (same seq) arrives 3us later at t=1_003_000, at the SAME price -- on its
    # own that would show zero advantage, which would be a trivial/uninteresting
    # model (the "same trade" always has the same price on both feeds). What
    # actually matters is what price a public-only bot would be acting on once
    # it catches up to that moment -- i.e. the next public trade for the same
    # market after that point. Here the public feed shows a further move to
    # 52.0 shortly after, which is what build_opportunities must surface.
    dz_trades = [_trade(1_000_000, price=50.0, seq=1, source=Source.DZ_FEED)]
    public_trades = [
        _trade(1_003_000, price=50.0, seq=1, source=Source.KALSHI_WS),
        _trade(1_004_000, price=52.0, seq=2, source=Source.KALSHI_WS),
    ]
    opps = build_opportunities(public_trades, dz_trades, window_ns=5_000_000)
    assert len(opps) == 1
    assert opps[0]["delta_ns"] == 3_000
    assert opps[0]["edge_price"] == 50.0
    assert opps[0]["public_price"] == 52.0


def test_build_opportunities_falls_back_to_edge_price_when_no_follow_trade():
    dz_trades = [_trade(1_000_000, price=50.0, seq=1, source=Source.DZ_FEED)]
    public_trades = [
        _trade(1_003_000, price=50.0, seq=1, source=Source.KALSHI_WS),
    ]
    opps = build_opportunities(public_trades, dz_trades, window_ns=5_000_000)
    assert len(opps) == 1
    assert opps[0]["edge_price"] == 50.0
    assert opps[0]["public_price"] == 50.0  # no later public trade -> fallback


def test_build_opportunities_ignores_follow_trade_outside_window():
    dz_trades = [_trade(1_000_000, price=50.0, seq=1, source=Source.DZ_FEED)]
    public_trades = [
        _trade(1_003_000, price=50.0, seq=1, source=Source.KALSHI_WS),
        _trade(1_003_000 + 10_000_000, price=99.0, seq=2, source=Source.KALSHI_WS),
    ]
    opps = build_opportunities(public_trades, dz_trades, window_ns=5_000_000)
    assert opps[0]["public_price"] == 50.0


def test_build_opportunities_no_matches_yields_empty_list():
    assert build_opportunities([], [], window_ns=5_000_000) == []
