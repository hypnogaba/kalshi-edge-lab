"""What each bot would actually have gotten, judged against one shared truth.

The trap this module avoids
---------------------------
If each bot is filled against its OWN view of the book, both bots always fill,
both look identical, and the demo proves nothing: a slow bot with a slow book is
internally consistent. The market, however, is a single sequence of events. So
every intent from either bot is judged against ONE ground-truth book timeline,
at the moment that bot actually decided.

The ground truth is the DoubleZero feed, because it is the least-delayed
observation of the venue available on this host. That does not tilt the result:
both bots are filled against the same book, by the same rule. The public-fed bot
loses only where it deserves to, i.e. where the quote it aimed at was already
gone by the time it decided.

Honesty / limitations (read before citing a number from this module)
--------------------------------------------------------------------
- Paper fills. No queue position, no fees, no partial fills, no size limits
  beyond the quoted size, and no market impact. Both bots get the same free
  pass, so the COMPARISON is meaningful even though the absolute P&L is not a
  promise of anything.
- Every intent is judged `reaction_ns` AFTER the bot decided, not at the instant
  it decided. Without that, the DoubleZero bot is judged against the very book
  snapshot it just acted on and fills essentially always -- a structural 100%
  that flatters us and measures nothing. The same reaction is applied to both
  bots, so the gap between them stays exactly the feed delta.
- The mark-out horizon is arbitrary. It is a way to say "was that a good price
  shortly after", not a claim about a real exit.
- A bot is charged nothing for intents that miss. Missing is free here; in the
  real world it costs opportunity, not money, which is the same thing.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from common.event import Side
from demo.book import TopOfBook
from demo.strategy import Intent

DEFAULT_MARKOUT_NS = 1_000_000_000  # 1 s
DEFAULT_REACTION_NS = 1_000_000     # 1 ms: decide, build the order, put it on the wire


@dataclass(frozen=True, slots=True)
class Fill:
    intent: Intent
    filled: bool
    price: float | None          # what the ground-truth book charged us
    reason: str                  # "filled" | "quote_gone" | "no_book"
    markout: float | None = None  # per contract, in price units; + is good


class GroundTruth:
    """A replayable timeline of top-of-book states, fed by the fastest source."""

    def __init__(self, max_per_market: int = 200_000) -> None:
        self._times: dict[str, list[int]] = {}
        self._books: dict[str, list[TopOfBook]] = {}
        self._max = max_per_market

    def record(self, book: TopOfBook) -> None:
        times = self._times.setdefault(book.market, [])
        books = self._books.setdefault(book.market, [])
        # Arrivals are monotonic on one clock, but never trust that blindly:
        # a same-nanosecond update must replace, not corrupt the ordering.
        if times and book.t_updated_ns < times[-1]:
            return
        if times and book.t_updated_ns == times[-1]:
            books[-1] = book
            return
        times.append(book.t_updated_ns)
        books.append(book)
        if len(times) > self._max:
            del times[: len(times) // 2]
            del books[: len(books) // 2]

    def state_at(self, market: str, t_ns: int) -> TopOfBook | None:
        """The last book state known at or before `t_ns`."""
        times = self._times.get(market)
        if not times:
            return None
        idx = bisect.bisect_right(times, t_ns) - 1
        if idx < 0:
            return None
        return self._books[market][idx]

    def settle(self, intent: Intent, markout_ns: int = DEFAULT_MARKOUT_NS,
               reaction_ns: int = DEFAULT_REACTION_NS) -> Fill:
        """Judge one intent against the shared book, as of the moment the order
        could actually have reached the venue."""
        t_arrives_ns = intent.t_decided_ns + reaction_ns
        book = self.state_at(intent.market, t_arrives_ns)
        if book is None:
            return Fill(intent=intent, filled=False, price=None, reason="no_book")

        if intent.side is Side.BUY:
            quote = book.ask
            if quote is None or quote > intent.limit_price:
                return Fill(intent=intent, filled=False, price=None, reason="quote_gone")
            price = min(quote, intent.limit_price)
        else:
            quote = book.bid
            if quote is None or quote < intent.limit_price:
                return Fill(intent=intent, filled=False, price=None, reason="quote_gone")
            price = max(quote, intent.limit_price)

        later = self.state_at(intent.market, t_arrives_ns + markout_ns)
        markout = None
        if later is not None and later.mid is not None:
            markout = later.mid - price if intent.side is Side.BUY else price - later.mid
        return Fill(intent=intent, filled=True, price=price, reason="filled",
                    markout=markout)


@dataclass
class Scoreboard:
    """Running totals for one bot. Plain numbers, no cleverness."""
    name: str
    intents: int = 0
    fills: int = 0
    missed: int = 0
    markout_sum: float = 0.0
    contracts: int = 0

    def add(self, fill: Fill) -> None:
        self.intents += 1
        if not fill.filled:
            self.missed += 1
            return
        self.fills += 1
        self.contracts += fill.intent.size
        if fill.markout is not None:
            self.markout_sum += fill.markout * fill.intent.size

    @property
    def fill_rate(self) -> float | None:
        return 100.0 * self.fills / self.intents if self.intents else None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "intents": self.intents,
            "fills": self.fills,
            "missed": self.missed,
            "fill_rate": round(self.fill_rate, 1) if self.fill_rate is not None else None,
            "contracts": self.contracts,
            "markout_total": round(self.markout_sum, 4),
            "markout_per_contract": (round(self.markout_sum / self.contracts, 5)
                                     if self.contracts else None),
        }
