"""Reference data off the wire, pinned to values read from the live feed.

Contract size decides how a DZ trade size is compared with Kalshi's public
contract count. Getting it wrong does not raise: it silently gives two bots
different thresholds, or reports a DOGE print as six million contracts.
"""
import pytest

from sources.dz_feed.registry import InstrumentRegistry

# symbol, qty_exp, price_exp, tick_size_raw, lot_size_raw -> observed live
LIVE = [
    ("KXBTCPERP", -8, -8, 100_000_000, 10_000),
    ("KXETHPERP", -8, -8, 10_000_000, 100_000),
    ("KXSOLPERP", -8, -8, 100_000, 10_000_000),
    ("KXDOGEPERP", -8, -8, 100, 10_000_000_000),
]


def registry_with(entries=LIVE) -> InstrumentRegistry:
    registry = InstrumentRegistry()
    for index, (symbol, qty_exp, price_exp, tick, lot) in enumerate(entries):
        registry.update(index, symbol, price_exp, qty_exp, source_id=1,
                        tick_size_raw=tick, lot_size_raw=lot, contract_value_raw=0)
    return registry


def test_btc_contract_size_matches_the_ratio_measured_against_the_public_feed():
    """1e-4 was measured independently on 40 live matched trades. If this drifts,
    every cross-feed size comparison is wrong."""
    btc = registry_with().by_symbol("KXBTCPERP")
    assert btc.contract_size == pytest.approx(1e-4)


def test_btc_tick_size_is_one_dollar():
    """A cross-check on the exponent: BTC perp prices move in whole dollars."""
    assert registry_with().by_symbol("KXBTCPERP").tick_size == pytest.approx(1.0)


def test_cheap_coins_have_large_contracts():
    """DOGE is 100 coins per contract. Assuming BTC's 1e-4 here is what turned a
    real print into '6,000,000 contracts'."""
    assert registry_with().by_symbol("KXDOGEPERP").contract_size == pytest.approx(100.0)
    assert registry_with().by_symbol("KXSOLPERP").contract_size == pytest.approx(0.1)
    assert registry_with().by_symbol("KXETHPERP").contract_size == pytest.approx(1e-3)


def test_contract_value_field_is_not_used():
    """The feed publishes contract_value as 0 for every perp; trusting it would
    make every size zero or a division blow up."""
    assert registry_with().by_symbol("KXBTCPERP").contract_value_raw == 0


def test_unknown_symbol_is_absent_not_invented():
    assert registry_with().by_symbol("KXNOPEPERP") is None
