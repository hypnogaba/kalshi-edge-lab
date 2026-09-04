"""Instrument registry for the DoubleZero Top-of-Book & Trades feed.

Maps InstrumentID (u32, from 0x03 Quote / 0x04 Trade) to the reference data
published in 0x02 InstrumentDefinition messages: symbol + the per-instrument
price/qty exponents needed to scale raw i64/u64 wire values into real numbers
(real = raw * 10**exponent). See sources/dz_feed/decoder.py and
https://github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    price_exp: int
    qty_exp: int
    source_id: int
    # Raw reference data. tick_size scales by price_exp, lot_size by qty_exp,
    # like every other value on the wire.
    tick_size_raw: int = 0
    lot_size_raw: int = 0
    contract_value_raw: int = 0   # published as 0 on every Kalshi perp: unusable

    @property
    def tick_size(self) -> float:
        """Smallest price increment. KXBTCPERP = 1.0, which matches the whole
        dollars BTC prices actually move in."""
        return self.tick_size_raw * 10 ** self.price_exp

    @property
    def contract_size(self) -> float:
        """One contract, in units of the underlying.

        This is what turns a DZ trade size back into a contract count
        comparable with Kalshi's public feed, which counts contracts. Verified
        for KXBTCPERP: lot_size here is 1e-4, exactly the size_dz/count_public
        ratio measured over 40 live matched trades. Note the feed's own
        contract_value field is published as 0 for every perp, so lot_size is
        the only usable source.
        """
        return self.lot_size_raw * 10 ** self.qty_exp


class InstrumentRegistry:
    def __init__(self) -> None:
        self._instruments: dict[int, Instrument] = {}
        # One registry is fed by both publisher arms (see sources/dz_feed/arms.py).
        # They agree on every InstrumentID today -- checked live, both publish the
        # same 18 ids for the same symbols -- but nothing on the wire promises it,
        # and if it ever stopped being true a shared registry would relabel one
        # market as another in silence. So the first symbol an id resolves to
        # wins, and a disagreement is counted where a reader can see it.
        self.symbol_conflicts = 0

    def update(self, instr_id: int, symbol: str, price_exp: int, qty_exp: int,
               source_id: int, tick_size_raw: int = 0, lot_size_raw: int = 0,
               contract_value_raw: int = 0) -> None:
        known = self._instruments.get(instr_id)
        if known is not None and known.symbol != symbol:
            self.symbol_conflicts += 1
            return
        self._instruments[instr_id] = Instrument(
            symbol=symbol, price_exp=price_exp, qty_exp=qty_exp, source_id=source_id,
            tick_size_raw=tick_size_raw, lot_size_raw=lot_size_raw,
            contract_value_raw=contract_value_raw)

    def by_symbol(self, symbol: str) -> Instrument | None:
        for instrument in self._instruments.values():
            if instrument.symbol == symbol:
                return instrument
        return None

    def get(self, instr_id: int) -> Instrument | None:
        return self._instruments.get(instr_id)
