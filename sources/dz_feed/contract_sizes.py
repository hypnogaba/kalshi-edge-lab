"""One market's own scale, shared between the two feeds.

Two numbers, both properties of the MARKET and not of any pipe, and both
published by only one of the two feeds -- the DoubleZero instrument definitions
carry them as lot_size and tick_size (see registry.Instrument):

  contract_size  puts the feeds on one axis. They report the same trade
                 differently:
                     DoubleZero:  price = dollars per unit of underlying,
                                  size  = underlying
                     Kalshi WS:   price = dollars per CONTRACT,
                                  count = contracts
                 so dollars-per-underlying = public_price / contract_size, and
                 contracts = dz_size / contract_size. Verified live on
                 KXBTCPERP (contract 1e-4, public price 7.7720 -> $77,720) and
                 KXETHPERP (contract 1e-3, public price 2.3938 -> $2,393.8,
                 where a flat 1e4 gave $23,938).

  tick_size      quantises the price for the match key. The two feeds reach the
                 same price by different arithmetic, so the key has to round --
                 but rounding to whole dollars, which is what this used to do,
                 throws the price away entirely on a cheap market: DOGE at
                 $0.089, KSHIB at $0.0054, WLD and ADA all round to 0, and XRP
                 and SUI both to 1. Rounding to the market's own tick keeps full
                 resolution everywhere AND lands each value on an integer, which
                 is the furthest a float can be from a rounding boundary. Live
                 ticks run from 1.0 (BTC) to 1e-7 (KSHIB).

Filled by whichever thread reads the DZ feed and read by the public side, hence
the lock. Unknown markets return None: reference data arrives within seconds of
joining the group, and until it does a market cannot be put on one axis without
guessing.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from sources.dz_feed.registry import InstrumentRegistry


@dataclass(frozen=True, slots=True)
class Axis:
    contract_size: float
    tick_size: float


class ContractSizes:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._axes: dict[str, Axis] = {}

    def _learn(self, registry: InstrumentRegistry, market: str) -> Axis | None:
        with self._lock:
            cached = self._axes.get(market)
        if cached is not None:
            return cached
        instrument = registry.by_symbol(market)
        if instrument is None:
            return None
        if instrument.contract_size <= 0 or instrument.tick_size <= 0:
            return None
        axis = Axis(instrument.contract_size, instrument.tick_size)
        with self._lock:
            self._axes[market] = axis
        return axis

    def learn_from(self, registry: InstrumentRegistry, market: str) -> float | None:
        """Contract size for `market`, looked up in DZ reference data and cached."""
        axis = self._learn(registry, market)
        return axis.contract_size if axis else None

    def axis_from(self, registry: InstrumentRegistry, market: str) -> Axis | None:
        """Both scales at once, for callers that key on price."""
        return self._learn(registry, market)

    def get(self, market: str) -> float | None:
        with self._lock:
            axis = self._axes.get(market)
        return axis.contract_size if axis else None

    def axis(self, market: str) -> Axis | None:
        with self._lock:
            return self._axes.get(market)

    def tick(self, market: str) -> float | None:
        """Smallest price increment, for callers that only need to quantise."""
        axis = self.axis(market)
        return axis.tick_size if axis else None

    def known(self) -> dict[str, float]:
        with self._lock:
            return {m: a.contract_size for m, a in self._axes.items()}
