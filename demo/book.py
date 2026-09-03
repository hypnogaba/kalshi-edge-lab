"""Per-market top of book, rebuilt from QUOTE events.

Both feeds decode to the same `Event`, so one implementation serves both sides
of the demo. A book instance is fed by exactly ONE source and therefore holds
that source's *view* of the market, which is the whole point: the public-fed
book lags the DoubleZero-fed book by the feed delta.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from common.event import Event, Kind, Side


@dataclass(frozen=True, slots=True)
class TopOfBook:
    """Best bid/ask for one market, with the arrival time of the last update."""
    market: str
    bid: float | None = None
    bid_size: float | None = None
    ask: float | None = None
    ask_size: float | None = None
    t_updated_ns: int = 0

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2


class BookState:
    """Top of book for every market seen on one feed."""

    def __init__(self) -> None:
        self._books: dict[str, TopOfBook] = {}

    def apply(self, event: Event) -> TopOfBook | None:
        """Fold a QUOTE event in. Returns the updated book, or None if the event
        is not a quote (trades are handled by the strategy, not the book)."""
        if event.kind is not Kind.QUOTE or event.price is None:
            return None
        book = self._books.get(event.market) or TopOfBook(market=event.market)
        if event.side is Side.BID:
            book = replace(book, bid=event.price, bid_size=event.size,
                           t_updated_ns=event.t_arrival_ns)
        elif event.side is Side.ASK:
            book = replace(book, ask=event.price, ask_size=event.size,
                           t_updated_ns=event.t_arrival_ns)
        else:
            return None
        self._books[event.market] = book
        return book

    def get(self, market: str) -> TopOfBook | None:
        return self._books.get(market)

    def markets(self) -> list[str]:
        return sorted(self._books)
