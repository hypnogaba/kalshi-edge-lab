"""The live race's join key: what the two feeds agree on, and at what resolution."""
import pytest

from scripts.dz_latency_race import _match_key

# Real ticks, off the feed's own instrument definitions (2026-09-04).
BTC, ETH, DOGE, KSHIB = 1.0, 0.1, 1e-6, 1e-7


def test_the_same_trade_from_both_feeds_lands_on_one_key():
    """DZ multiplies a raw i64 by 1e-8; the public side divides a decimal
    string by the contract size. The two arrive at the same price by different
    arithmetic, and the key has to absorb that."""
    exch_ms = 1788502115168
    dz = _match_key("KXBTCPERP", 80961.00000000001, 617.0, exch_ms, BTC)
    public = _match_key("KXBTCPERP", 8.0961 / 1e-4, 617.0, exch_ms, BTC)
    assert dz == public


@pytest.mark.parametrize("market,price_a,price_b,tick", [
    # Every one of these collapsed to the same key when the price was rounded
    # to whole dollars: DOGE and KSHIB both to 0.
    ("KXDOGEPERP", 0.089196, 0.089201, DOGE),
    ("KXKSHIBPERP", 0.0054368, 0.0054371, KSHIB),
    ("KXETHPERP", 2514.8, 2515.3, ETH),
])
def test_two_different_prices_are_two_different_keys(market, price_a, price_b, tick):
    exch_ms = 1788502115168
    assert _match_key(market, price_a, 1.0, exch_ms, tick) != \
           _match_key(market, price_b, 1.0, exch_ms, tick)


def test_a_cheap_market_is_not_keyed_on_time_and_size_alone():
    """The bug in one line: at $0.089 a DOGE print rounded to a price of 0, so
    the key carried no price at all."""
    key = _match_key("KXDOGEPERP", 0.089196, 1.0, 1788502115168, DOGE)
    assert key[2] != 0
    assert key[2] == round(0.089196 / DOGE)


def test_a_price_lands_on_a_whole_number_of_ticks():
    """Which is the point: a real trade sits on a tick, so the quotient is an
    integer and rounding it is as far from a boundary as a float can get.
    Rounding dollars put ETH at 2514.75 exactly on one."""
    for i in range(1, 50):
        price = ETH * i
        assert abs(price / ETH - round(price / ETH)) < 1e-6


def test_market_time_and_size_still_separate_trades():
    base = ("KXBTCPERP", 80961.0, 617.0, 1788502115168, BTC)
    key = _match_key(*base)
    assert key != _match_key("KXETHPERP", *base[1:])
    assert key != _match_key(base[0], base[1], 618.0, base[3], BTC)
    assert key != _match_key(base[0], base[1], base[2], base[3] + 1, BTC)
