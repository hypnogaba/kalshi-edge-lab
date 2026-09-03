"""One market's contract size, shared between the two feeds.

Contract size is a property of the market, not of a pipe, but only one of the
two feeds publishes it: the DoubleZero instrument definitions carry it as
lot_size (see registry.Instrument.contract_size). Both feeds need it, because
they report the same trade on different axes:

    DoubleZero:  price = dollars per unit of underlying, size = underlying
    Kalshi WS:   price = dollars per CONTRACT,           count = contracts

so dollars-per-underlying = public_price / contract_size, and contracts =
dz_size / contract_size. Verified live on KXBTCPERP (contract 1e-4, public
price 7.7720 -> $77,720) and KXETHPERP (contract 1e-3, public price 2.3938 ->
$2,393.8, where a flat 1e4 gave $23,938).

Filled by whichever thread reads the DZ feed and read by the public side, hence
the lock. Unknown markets return None: reference data arrives within seconds of
joining the group, and until it does a market cannot be put on one axis without
guessing.
"""
from __future__ import annotations

import threading

from sources.dz_feed.registry import InstrumentRegistry


class ContractSizes:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sizes: dict[str, float] = {}

    def learn_from(self, registry: InstrumentRegistry, market: str) -> float | None:
        """Look the market up in DZ reference data, caching what it finds."""
        with self._lock:
            cached = self._sizes.get(market)
        if cached is not None:
            return cached
        instrument = registry.by_symbol(market)
        if instrument is None or instrument.contract_size <= 0:
            return None
        with self._lock:
            self._sizes[market] = instrument.contract_size
        return instrument.contract_size

    def get(self, market: str) -> float | None:
        with self._lock:
            return self._sizes.get(market)

    def known(self) -> dict[str, float]:
        with self._lock:
            return dict(self._sizes)
