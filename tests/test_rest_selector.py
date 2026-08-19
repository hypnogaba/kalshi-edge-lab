from sources.kalshi_rest.selector import nearest_markets, parse_strike


def test_parse_strike_threshold_and_bucket():
    assert parse_strike("KXBTC-26AUG1917-T73299.99") == 73299.99
    assert parse_strike("KXBTC-26AUG1912-B68550") == 68550.0
    assert parse_strike("KXBTC15M-26AUG191145-45") is None  # no T/B strike suffix
    assert parse_strike("garbage") is None


def test_nearest_markets_sorts_by_distance_to_spot():
    tickers = ["KXBTC-X-B68000", "KXBTC-X-B69000", "KXBTC-X-B68500", "KXBTC-X-T99999.99"]
    out = nearest_markets(tickers, spot=68550.0, n=2)
    assert out == ["KXBTC-X-B68500", "KXBTC-X-B69000"]
