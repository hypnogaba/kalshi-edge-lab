"""Decode Kalshi's perps/margin WS JSON into normalized Events.

Pinned against real frames off `wss://external-api-margin-ws.kalshi.com`,
recorded into `tests/data/margin_trades.jsonl`, not against the docs:

    {"type":"trade","sid":1,"seq":1,"msg":{
       "trade_id":"0721c72a-8859-b8d2-6603-25bd482f0d18",
       "market_ticker":"KXBTCPERP","price":"8.0961","count":"617.00",
       "taker_side":"ask","ts_ms":1788502115168}}

This file used to decode the OTHER socket, `/trade-api/ws/v2`, which carries
Kalshi's event markets. Its field names are real there and wrong here, and
nothing said so:

    yes_price / no_price   the perps feed sends `price`      -> price was always None
    taker_side yes|no      the perps feed sends bid|ask      -> side was always None
    ts (seconds)           the perps feed sends `ts_ms`      -> exch_ts_ns never set
    numbers                the perps feed sends STRINGS      -> "617.00", not 617

A matcher fed by that decoder skipped every price comparison in silence. The
lab moved to perps and this side was never moved with it.

Two things this deliberately does NOT do.

`price` is left as the venue sends it: dollars per CONTRACT. Putting it on the
DoubleZero feed's axis needs the market's contract size, which only the DZ
reference data carries, so the caller does it (see
sources/dz_feed/contract_sizes.py). Scaling by a constant here is how the race
came to measure BTC alone.

`seq` is left as None. The frame carries one, but it is a per-subscription
message counter -- it increments 1, 2, 3 across consecutive trades on any
market -- while the DoubleZero feed's `seq` is the venue's u64 trade id. They
are different id spaces. Matching on the pair joins unrelated trades, which is
what race/match.py used to do. The venue's real trade id here is a UUID, and
`Event` has nowhere to put it; it is not needed, because both feeds carry the
execution timestamp, price and size, which is what the join uses.

Book reconstruction is not here either: the top of book has to be rebuilt from
orderbook_snapshot + orderbook_delta, which is stateful, and
demo/public_feed.py already does it against the same live socket.
"""
import orjson

from common.event import Event, Kind, Side, Source

# taker_side is the aggressor. Measured over 219 live trades: "bid" printed at
# or above the ask (an aggressive BUY) and never at or below the bid.
_SIDE = {"bid": Side.BUY, "ask": Side.SELL}


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    """TRADE events from one margin-WS frame. Anything else yields nothing."""
    msg = orjson.loads(raw)
    if msg.get("type") != "trade":
        return []
    body = msg.get("msg") or {}
    try:
        market = body["market_ticker"]
        price = float(body["price"])
        size = float(body["count"])
        exch_ts_ns = int(body["ts_ms"]) * 1_000_000
    except (KeyError, TypeError, ValueError):
        return []
    return [Event(
        source=Source.MARGIN_WS, t_arrival_ns=t_arrival_ns, market=market,
        kind=Kind.TRADE, price=price, size=size,
        side=_SIDE.get(body.get("taker_side")), seq=None,
        exch_ts_ns=exch_ts_ns)]
