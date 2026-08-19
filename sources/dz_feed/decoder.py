"""DoubleZero Top-of-Book & Trades feed decoder (schema v3).

Wire format: https://github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md
All integers little-endian. Prices are i64, quantities u64, each scaled by the
instrument's Price/Qty Exponent from the 0x02 InstrumentDefinition message:
real = raw * 10**exponent.

Frame header (24B): Magic u16 (0x445A), Schema Ver u8 (=3), Channel ID u8,
Sequence Number u64, Send Timestamp ts_ns u64, Msg Count u8, Reset Count u8,
Frame Length u16.

App message header (4B): Type u8, Length u8 (includes header), Flags u16.
A decoder MUST skip unknown message types using the Length field.

Message types implemented:
  0x01 Heartbeat (16B)          -> no event
  0x02 InstrumentDefinition     -> registry.update(...), no event
       (130B, refdata: InstrumentID u32 @4, SourceID u16 @8, Symbol
        char[64] @10, ... Asset Class u8 @90, Price Exponent i8 @91,
        Qty Exponent i8 @92, ...)
  0x03 Quote (60B)              -> up to 2 QUOTE events (bid + ask)
  0x04 Trade (52B)              -> 1 TRADE event
  0x06 EndOfSession (12B)       -> no event
  unknown                       -> skipped via Length

NOTE on Trade layout: the field order after Aggressor Side is Source
Timestamp (ts_ns @12), Trade Price (price @20), Trade Quantity (qty @28),
Trade ID (u64 @36), Cumulative Volume (qty @44) -- per the published spec,
NOT the "Trade ID, Price, Qty, Source ts_ns" order implied by the plan draft.
"""
import struct

from common.event import Event, Kind, Side, Source
from sources.dz_feed.registry import InstrumentRegistry

_MAGIC = 0x445A
_SCHEMA_VER = 3

_FRAME_HEADER = struct.Struct("<HBBQQBBH")
_MSG_HEADER = struct.Struct("<BBH")

# Body immediately after the 4B app message header.
_INSTRUMENT_DEFINITION_BODY = struct.Struct("<IH64s8s8sBbbBqQQQBBH")
_QUOTE_BODY = struct.Struct("<IHBBQqQqQHH")
_TRADE_BODY = struct.Struct("<IHBBQqQQQ")


class DzDecoder:
    """Decodes DZ Top-of-Book & Trades v3 frames into normalized Events."""

    def __init__(self, registry: InstrumentRegistry | None = None) -> None:
        self.registry = registry if registry is not None else InstrumentRegistry()

    def decode(self, raw: bytes, t_arrival_ns: int) -> list[Event]:
        if len(raw) < _FRAME_HEADER.size:
            return []
        (magic, schema_ver, _channel_id, seq, _send_ts_ns, msg_count,
         _reset_count, _frame_length) = _FRAME_HEADER.unpack_from(raw, 0)
        if magic != _MAGIC or schema_ver != _SCHEMA_VER:
            return []

        events: list[Event] = []
        offset = _FRAME_HEADER.size
        for _ in range(msg_count):
            if offset + _MSG_HEADER.size > len(raw):
                break
            msg_type, msg_length, _flags = _MSG_HEADER.unpack_from(raw, offset)
            if msg_length == 0 or offset + msg_length > len(raw):
                break

            if msg_type == 0x02:
                self._decode_instrument_definition(raw, offset)
            elif msg_type == 0x03:
                events.extend(self._decode_quote(raw, offset, t_arrival_ns, seq))
            elif msg_type == 0x04:
                events.append(self._decode_trade(raw, offset, t_arrival_ns))
            # 0x01 Heartbeat, 0x06 EndOfSession, and unknown types carry no event.

            offset += msg_length
        return events

    def _decode_instrument_definition(self, raw: bytes, offset: int) -> None:
        (instr_id, source_id, symbol_raw, _leg1, _leg2, _asset_class, price_exp,
         qty_exp, _market_model, _tick_size, _lot_size, _contract_value, _expiry,
         _settle_type, _price_bound, _manifest_seq) = _INSTRUMENT_DEFINITION_BODY.unpack_from(
            raw, offset + _MSG_HEADER.size)
        symbol = symbol_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        self.registry.update(instr_id, symbol, price_exp, qty_exp, source_id)

    def _market_and_exponents(self, instr_id: int) -> tuple[str, int, int]:
        instrument = self.registry.get(instr_id)
        if instrument is None:
            return str(instr_id), 0, 0
        return instrument.symbol, instrument.price_exp, instrument.qty_exp

    def _decode_quote(self, raw: bytes, offset: int, t_arrival_ns: int,
                       frame_seq: int) -> list[Event]:
        (instr_id, _source_id, _update_flags, _reserved, _source_ts_ns, bid_price_raw,
         bid_qty_raw, ask_price_raw, ask_qty_raw, _bid_src_count,
         _ask_src_count) = _QUOTE_BODY.unpack_from(raw, offset + _MSG_HEADER.size)
        market, price_exp, qty_exp = self._market_and_exponents(instr_id)
        return [
            Event(source=Source.DZ_FEED, t_arrival_ns=t_arrival_ns, market=market,
                  kind=Kind.QUOTE, side=Side.BID, price=bid_price_raw * 10**price_exp,
                  size=bid_qty_raw * 10**qty_exp, seq=frame_seq),
            Event(source=Source.DZ_FEED, t_arrival_ns=t_arrival_ns, market=market,
                  kind=Kind.QUOTE, side=Side.ASK, price=ask_price_raw * 10**price_exp,
                  size=ask_qty_raw * 10**qty_exp, seq=frame_seq),
        ]

    def _decode_trade(self, raw: bytes, offset: int, t_arrival_ns: int) -> Event:
        (instr_id, _source_id, aggressor_side, _trade_flags, _source_ts_ns, price_raw,
         qty_raw, trade_id, _cum_volume) = _TRADE_BODY.unpack_from(
            raw, offset + _MSG_HEADER.size)
        market, price_exp, qty_exp = self._market_and_exponents(instr_id)
        side = Side.BUY if aggressor_side == 1 else Side.SELL if aggressor_side == 2 else None
        return Event(source=Source.DZ_FEED, t_arrival_ns=t_arrival_ns, market=market,
                     kind=Kind.TRADE, side=side, price=price_raw * 10**price_exp,
                     size=qty_raw * 10**qty_exp, seq=trade_id)


_default_decoder = DzDecoder()


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    """Module-level convenience using a default shared registry/decoder."""
    return _default_decoder.decode(raw, t_arrival_ns)
