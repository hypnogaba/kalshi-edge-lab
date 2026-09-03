"""Kalshi's public perps WebSocket, turned into the same `Event` type as the feed.

Everything here was pinned against the live socket, not against the docs:

- Numbers arrive as STRINGS ("7.7720", "13.00"), and `price` is dollars per
  CONTRACT, not per unit of the underlying. Dividing by the market's contract
  size is what puts it on the DZ feed's axis. A flat 1e4 is right for BTC only
  because its contract happens to be 1e-4; on ETH (contract 1e-3) it reported
  the same $2,393.8 trade as $23,938, and the two copies of that trade then
  failed to pair at all.
- `taker_side` is "bid"/"ask", not "yes"/"no". Measured over 219 live trades:
  taker_side="bid" printed at or above the ask (an aggressive BUY) and never at
  or below the bid; taker_side="ask" printed at or below the bid. So bid -> BUY.
  Reading it the other way round inverts the whole strategy.
- The `ticker` channel carries bid/ask but only about once per second per
  market, which would make the public bot look artificially slow. The public
  top of book has to be rebuilt from `orderbook_snapshot` + `orderbook_delta`,
  which is what a trader on the public path actually does. Measured in one
  minute: 22330 deltas vs 72 tickers.
"""
from __future__ import annotations

from collections.abc import Callable

from common.event import Event, Kind, Side, Source

_BID, _ASK = "bid", "ask"

# A market whose contract size is not known yet cannot be put on the DZ feed's
# axis, so it is dropped rather than guessed.
ContractSizeLookup = Callable[[str], float | None]


class PublicFeed:
    """Stateful decoder: holds the public order book so it can emit top-of-book
    quotes. One instance per connection.

    `contract_size` maps a market to the size of one contract in the
    underlying; see sources/dz_feed/contract_sizes.py for where it comes from
    and why both feeds need it.
    """

    def __init__(self, contract_size: ContractSizeLookup) -> None:
        self._contract_size = contract_size
        self._levels: dict[str, dict[str, dict[float, float]]] = {}
        self._best: dict[str, tuple[float | None, float | None]] = {}

    def on_message(self, payload: dict, t_ns: int) -> list[Event]:
        kind = payload.get("type")
        msg = payload.get("msg") or {}
        market = msg.get("market_ticker")
        if not market or self._contract_size(market) is None:
            return []
        if kind == "trade":
            return self._trade(market, msg, t_ns)
        if kind == "orderbook_snapshot":
            self._levels[market] = {
                side: {float(price): float(size) for price, size in (msg.get(side) or [])}
                for side in (_BID, _ASK)}
            return self._quotes_if_changed(market, t_ns)
        if kind == "orderbook_delta":
            return self._delta(market, msg, t_ns)
        return []

    def _trade(self, market: str, msg: dict, t_ns: int) -> list[Event]:
        try:
            price = float(msg["price"]) / self._contract_size(market)
            size = float(msg["count"])
            exch_ts_ns = int(msg["ts_ms"]) * 1_000_000
        except (KeyError, TypeError, ValueError):
            return []
        side = Side.BUY if msg.get("taker_side") == _BID else Side.SELL
        return [Event(source=Source.MARGIN_WS, t_arrival_ns=t_ns, market=market,
                      kind=Kind.TRADE, side=side, price=price, size=size,
                      exch_ts_ns=exch_ts_ns)]

    def _delta(self, market: str, msg: dict, t_ns: int) -> list[Event]:
        side = msg.get("side")
        if side not in (_BID, _ASK):
            return []
        book = self._levels.setdefault(market, {_BID: {}, _ASK: {}})
        try:
            price = float(msg["price"])
            size = book[side].get(price, 0.0) + float(msg["delta"])
        except (KeyError, TypeError, ValueError):
            return []
        if size > 0:
            book[side][price] = size
        else:
            book[side].pop(price, None)
        return self._quotes_if_changed(market, t_ns)

    def _quotes_if_changed(self, market: str, t_ns: int) -> list[Event]:
        """Emit quotes only when the TOP of book moved. The book churns deep
        down constantly; a bot only ever acts on the top, and re-emitting an
        unchanged top would just add noise to every downstream count."""
        book = self._levels.get(market)
        if not book:
            return []
        bid = max(book[_BID], default=None)
        ask = min(book[_ASK], default=None)
        if self._best.get(market) == (bid, ask):
            return []
        self._best[market] = (bid, ask)
        events = []
        for side, price in ((Side.BID, bid), (Side.ASK, ask)):
            if price is None:
                continue
            size = book[_BID if side is Side.BID else _ASK][price]
            events.append(Event(source=Source.MARGIN_WS, t_arrival_ns=t_ns,
                                market=market, kind=Kind.QUOTE, side=side,
                                price=price / self._contract_size(market), size=size))
        return events

    def best(self, market: str) -> tuple[float | None, float | None]:
        """Best (bid, ask) in dollars per unit of underlying, or (None, None)."""
        size = self._contract_size(market)
        bid, ask = self._best.get(market, (None, None))
        if size is None:
            return (None, None)
        return (bid / size if bid is not None else None,
                ask / size if ask is not None else None)
