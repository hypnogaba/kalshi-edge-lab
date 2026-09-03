"""The demo strategy: follow the print, take the quote that has not moved yet.

Deliberately the simplest rule that is *latency-native*, i.e. one where being
earlier is the entire advantage and no forecasting skill is involved:

    A large aggressive trade prints. That print is information: someone just
    paid up. If the resting quote on the same side has not been pulled yet, take
    it. Whoever learns of the print first has the better chance of finding that
    quote still there.

No edge is claimed beyond speed. A slower copy of this same strategy is the
control group, which is exactly what the demo runs side by side.

The strategy is feed-agnostic: it consumes normalized `Event`s and holds its own
`BookState`, so an instance sees the market only as fast as the feed wired into
it.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.event import Event, Kind, Side
from demo.book import BookState, TopOfBook


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Tuning. Sizes are in contracts, times in nanoseconds."""
    min_print_size: float = 50.0      # ignore prints smaller than this
    order_size: int = 1               # contracts per intent
    max_position: int = 5             # per market, absolute
    cooldown_ns: int = 2_000_000_000  # per market, after acting


@dataclass(frozen=True, slots=True)
class Intent:
    """A decision to take a resting quote, stamped when the decision was made."""
    market: str
    side: Side                # Side.BUY -> lift the ask; Side.SELL -> hit the bid
    limit_price: float        # the quote we are trying to take, as our feed saw it
    size: int
    t_decided_ns: int         # our feed's arrival time of the print that triggered us
    trigger_price: float
    trigger_size: float
    trigger_exch_ts_ns: int | None   # venue timestamp of the print: the join key


class FollowThePrint:
    """One instance = one bot = one feed. Not thread-safe by design; each bot
    runs in its own task and never shares state with the other side."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self.book = BookState()
        self._position: dict[str, int] = {}
        self._cooldown_until_ns: dict[str, int] = {}

    def position(self, market: str) -> int:
        return self._position.get(market, 0)

    def on_event(self, event: Event) -> Intent | None:
        """Fold one event in. Returns an Intent when the rule fires, else None."""
        if event.kind is Kind.QUOTE:
            self.book.apply(event)
            return None
        if event.kind is not Kind.TRADE:
            return None
        return self._on_trade(event)

    def _on_trade(self, event: Event) -> Intent | None:
        cfg = self.config
        if event.price is None or event.size is None or event.size < cfg.min_print_size:
            return None
        if event.t_arrival_ns < self._cooldown_until_ns.get(event.market, 0):
            return None
        book = self.book.get(event.market)
        if book is None:
            return None

        side, limit = self._target_quote(event, book)
        if side is None or limit is None:
            return None

        signed = cfg.order_size if side is Side.BUY else -cfg.order_size
        if abs(self.position(event.market) + signed) > cfg.max_position:
            return None

        self._position[event.market] = self.position(event.market) + signed
        self._cooldown_until_ns[event.market] = event.t_arrival_ns + cfg.cooldown_ns
        return Intent(market=event.market, side=side, limit_price=limit,
                      size=cfg.order_size, t_decided_ns=event.t_arrival_ns,
                      trigger_price=event.price, trigger_size=event.size,
                      trigger_exch_ts_ns=event.exch_ts_ns)

    @staticmethod
    def _target_quote(event: Event, book: TopOfBook) -> tuple[Side | None, float | None]:
        """A buy print means demand: try to lift the ask, but only while the ask
        is still at or below the print (a stale quote). Symmetric for a sell."""
        if event.side is Side.BUY:
            if book.ask is not None and book.ask <= event.price:
                return Side.BUY, book.ask
            return None, None
        if event.side is Side.SELL:
            if book.bid is not None and book.bid >= event.price:
                return Side.SELL, book.bid
            return None, None
        return None, None
