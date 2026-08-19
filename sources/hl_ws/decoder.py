"""Decode raw public Hyperliquid WS JSON into normalized Events.
Message shapes verified against live wss://api.hyperliquid.xyz/ws captures:
trades: {"channel":"trades","data":[{"coin","side":"B"|"A","px","sz","time","tid",...}]}
bbo: {"channel":"bbo","data":{"coin","time","bbo":[bid|None,ask|None]}}"""
import orjson

from common.event import Event, Kind, Side, Source

_TRADE_SIDE = {"B": Side.BUY, "A": Side.SELL}


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    msg = orjson.loads(raw)
    channel = msg.get("channel")
    data = msg.get("data")

    if channel == "trades":
        events: list[Event] = []
        for trade in data or []:
            events.append(Event(
                source=Source.HL_WS, t_arrival_ns=t_arrival_ns, market=trade.get("coin", ""),
                kind=Kind.TRADE, price=float(trade["px"]), size=float(trade["sz"]),
                side=_TRADE_SIDE.get(trade.get("side")), seq=trade.get("tid")))
        return events

    if channel == "bbo":
        market = data.get("coin", "")
        time = data.get("time")
        bbo = data.get("bbo") or [None, None]
        events = []
        for level, side_enum in zip(bbo, (Side.BID, Side.ASK)):
            if level is None:
                continue
            events.append(Event(
                source=Source.HL_WS, t_arrival_ns=t_arrival_ns, market=market,
                kind=Kind.QUOTE, price=float(level["px"]), size=float(level["sz"]),
                side=side_enum, seq=time))
        return events

    return []
