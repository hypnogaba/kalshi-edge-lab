"""Normalized market event. All sources decode to this type."""
from dataclasses import dataclass
from enum import Enum


class Source(str, Enum):
    KALSHI_WS = "kalshi_ws"
    KALSHI_REST = "kalshi_rest"
    MARGIN_WS = "margin_ws"  # Kalshi public perps/margin WebSocket (external-api-margin-ws)
    DZ_FEED = "dz_feed"


class Kind(str, Enum):
    TRADE = "trade"
    BOOK_DELTA = "book_delta"
    BOOK_SNAPSHOT = "book_snapshot"
    QUOTE = "quote"


class Side(str, Enum):
    YES = "yes"
    NO = "no"
    BID = "bid"
    ASK = "ask"
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Event:
    source: Source
    t_arrival_ns: int
    market: str
    kind: Kind
    price: int | float | None = None
    size: int | float | None = None
    side: Side | None = None
    seq: int | None = None
    # Venue-assigned exchange timestamp of the event (nanoseconds), when the feed
    # carries one. Same trade on two feeds shares this, so it is the join key for
    # the latency race (arrival times differ; the exchange timestamp does not).
    exch_ts_ns: int | None = None
