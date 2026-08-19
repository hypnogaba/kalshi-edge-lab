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


class InstrumentRegistry:
    def __init__(self) -> None:
        self._instruments: dict[int, Instrument] = {}

    def update(self, instr_id: int, symbol: str, price_exp: int, qty_exp: int,
               source_id: int) -> None:
        self._instruments[instr_id] = Instrument(
            symbol=symbol, price_exp=price_exp, qty_exp=qty_exp, source_id=source_id)

    def get(self, instr_id: int) -> Instrument | None:
        return self._instruments.get(instr_id)
