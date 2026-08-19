"""Decode raw Kalshi WS JSON into normalized Events.
Snapshot/control shapes verified against real demo captures (docs/feed-notes.md);
trade/delta field names from Kalshi docs, pending prod verification."""
import orjson

from common.event import Event, Kind, Side, Source

_SIDE = {"yes": Side.YES, "no": Side.NO}


def _price_from_trade(msg: dict) -> int | None:
    side = msg.get("taker_side")
    if side == "no" and "no_price" in msg:
        return msg.get("no_price")
    return msg.get("yes_price")


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    msg = orjson.loads(raw)
    typ = msg.get("type")
    body = msg.get("msg", {})
    market = body.get("market_ticker", "")
    seq = msg.get("seq")

    if typ == "trade":
        return [Event(
            source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
            kind=Kind.TRADE, price=_price_from_trade(body),
            size=body.get("count"), side=_SIDE.get(body.get("taker_side")), seq=seq)]

    if typ == "orderbook_delta":
        return [Event(
            source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
            kind=Kind.BOOK_DELTA, price=body.get("price"),
            size=body.get("delta"), side=_SIDE.get(body.get("side")), seq=seq)]

    if typ == "orderbook_snapshot":
        events: list[Event] = []
        for side_key, side_enum in (("yes", Side.YES), ("no", Side.NO)):
            for level in body.get(side_key, []) or []:
                events.append(Event(
                    source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
                    kind=Kind.BOOK_SNAPSHOT, price=level[0], size=level[1], side=side_enum, seq=seq))
        return events

    return []
