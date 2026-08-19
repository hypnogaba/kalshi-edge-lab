"""Decode tagged public-REST frames into normalized Events.
Trade prices are dollar strings (e.g. "0.0100" -> 1 cent); count is a float string."""
import orjson

from common.event import Event, Kind, Side, Source

_SIDE = {"yes": Side.YES, "no": Side.NO}


def _cents(dollar_str: str) -> int:
    return round(float(dollar_str) * 100)


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    frame = orjson.loads(raw)
    kind = frame.get("kind")
    ticker = frame.get("ticker", "")
    data = frame.get("data", {})

    if kind == "trade":
        side = _SIDE.get(data.get("taker_side"))
        price = _cents(data["no_price_dollars"]) if side == Side.NO else _cents(data["yes_price_dollars"])
        return [Event(
            source=Source.KALSHI_REST, t_arrival_ns=t_arrival_ns, market=ticker,
            kind=Kind.TRADE, price=price, size=int(float(data["count_fp"])),
            side=side, seq=None)]

    if kind == "orderbook":
        events: list[Event] = []
        for side_key, side_enum in (("yes", Side.YES), ("no", Side.NO)):
            for level in data.get(side_key) or []:
                events.append(Event(
                    source=Source.KALSHI_REST, t_arrival_ns=t_arrival_ns, market=ticker,
                    kind=Kind.BOOK_SNAPSHOT, price=level[0], size=level[1], side=side_enum, seq=None))
        return events

    return []
