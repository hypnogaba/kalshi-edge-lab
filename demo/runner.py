"""Run the same strategy twice, once per feed, and pair up their decisions.

One process, one clock, two bots:

    DoubleZero multicast (AF_PACKET on doublezero1) --> bot "doublezero"
    Kalshi public perps WebSocket                   --> bot "public"

Both bots are `demo.strategy.FollowThePrint` with identical config. Each holds
its own book, built from its own feed, so each sees the market exactly as fast
as its pipe delivers. Every intent either bot produces is then judged against
one shared ground-truth book (`demo.fills.GroundTruth`) at the moment that bot
decided -- see that module for why the judging is shared and what the paper fill
model does and does not model.

Decisions triggered by the SAME underlying print are paired into a `Duel` using
the venue's own (market, exchange-timestamp-ms, price, contracts) key, the same
join key the latency race uses. A duel is what the dashboard shows: one real
trade, two bots, two outcomes.

Writes data/demo_state.json. Places no orders.

Run (needs CAP_NET_RAW for AF_PACKET + a Kalshi PROD key in .env):
  sudo .venv/bin/python -m demo.runner --link doublezero1
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import orjson

from common.clock import now_ns
from common.config import kalshi_prod
from common.event import Event, Kind
from common.ws_client import ReconnectingWS
from demo.fills import DEFAULT_MARKOUT_NS, DEFAULT_REACTION_NS, Fill, GroundTruth, Scoreboard
from demo.public_feed import PublicFeed
from demo.strategy import FollowThePrint, Intent, StrategyConfig
from sources.dz_feed.decoder import DzDecoder
from sources.kalshi_ws.auth import KalshiSigner

_log = logging.getLogger(__name__)

MARGIN_WS_URL = "wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin"
MARGIN_WS_PATH = "/trade-api/ws/v2/margin"
_ETH_P_IP = 0x0800
_DUEL_TTL_NS = 30 * 1_000_000_000

# Only markets whose contract size has been VERIFIED against both feeds belong
# here. The DZ feed reports trade size in the underlying, the public feed in
# contracts, and the ratio between them is the market's contract size. Measured
# on live matched trades: KXBTCPERP = 1e-4 exactly (40 matches). Assuming that
# constant holds everywhere gives the two bots different effective thresholds on
# every other market, which would quietly rig the comparison -- so a market
# stays out until its ratio is measured the same way.
CONTRACT_SIZE = {"KXBTCPERP": 1e-4}
PERP_TICKERS = sorted(CONTRACT_SIZE)

DZ = "doublezero"
PUBLIC = "public"


def duel_key(market: str, dollars: float, contracts: float, exch_ts_ns: int) -> tuple:
    """Same join key as the latency race: the venue's own view of one trade."""
    return (market, exch_ts_ns // 1_000_000, round(dollars), round(contracts))


@dataclass
class Duel:
    """One print, as acted on by each bot. Either side may be missing: a bot that
    never fired (cooldown, position cap, quote already moved) is a real outcome,
    not a gap, and is reported as `acted: false`."""
    key: tuple
    market: str
    trigger_price: float
    trigger_size: float
    created_wall_ns: int
    sides: dict[str, Fill] = field(default_factory=dict)

    def add(self, name: str, fill: Fill) -> None:
        self.sides.setdefault(name, fill)

    def as_dict(self) -> dict:
        def side(name: str) -> dict:
            fill = self.sides.get(name)
            if fill is None:
                return {"acted": False}
            return {"acted": True, "filled": fill.filled, "price": fill.price,
                    "reason": fill.reason, "t_ns": fill.intent.t_decided_ns,
                    "side": fill.intent.side.value}
        out = {"market": self.market, "trigger_price": self.trigger_price,
               "trigger_size": self.trigger_size,
               DZ: side(DZ), PUBLIC: side(PUBLIC)}
        dz_fill, pub_fill = self.sides.get(DZ), self.sides.get(PUBLIC)
        if dz_fill is not None and pub_fill is not None:
            out["lead_ms"] = round(
                (pub_fill.intent.t_decided_ns - dz_fill.intent.t_decided_ns) / 1e6, 3)
        return out


class DemoState:
    """Everything the two bots share. Guarded by one lock; the DZ reader runs in
    a thread and the public WS in the event loop."""

    def __init__(self, config: StrategyConfig, markout_ns: int,
                 reaction_ns: int = DEFAULT_REACTION_NS) -> None:
        self._lock = threading.Lock()
        self._markout_ns = markout_ns
        self._reaction_ns = reaction_ns
        self.truth = GroundTruth()
        self.bots = {DZ: FollowThePrint(config), PUBLIC: FollowThePrint(config)}
        self.boards = {DZ: Scoreboard(DZ), PUBLIC: Scoreboard(PUBLIC)}
        self._pending: deque[tuple[str, Intent, tuple]] = deque()
        self._duels: dict[tuple, Duel] = {}
        self._recent: deque[Duel] = deque(maxlen=40)
        self.counts = {DZ: 0, PUBLIC: 0}
        self.started_ns = now_ns()

    def on_event(self, name: str, event: Event) -> None:
        with self._lock:
            self.counts[name] += 1
            # Ground truth is the least-delayed observation available.
            if name == DZ and event.kind is Kind.QUOTE:
                book = self.bots[DZ].book.apply(event)
                if book is not None:
                    self.truth.record(book)
            intent = self.bots[name].on_event(event)
            if intent is not None and event.exch_ts_ns:
                key = duel_key(event.market, event.price, event.size, event.exch_ts_ns)
                self._pending.append((name, intent, key))

    def settle_due(self) -> None:
        """Judge intents once the mark-out horizon has passed. The fill decision
        itself only ever reads book states at or before the decision, so waiting
        changes nothing about it."""
        now = now_ns()
        with self._lock:
            horizon = self._markout_ns + self._reaction_ns
            while self._pending and now - self._pending[0][1].t_decided_ns > horizon:
                name, intent, key = self._pending.popleft()
                fill = self.truth.settle(intent, self._markout_ns, self._reaction_ns)
                self.boards[name].add(fill)
                duel = self._duels.get(key)
                if duel is None:
                    duel = Duel(key=key, market=intent.market,
                                trigger_price=intent.trigger_price,
                                trigger_size=intent.trigger_size,
                                created_wall_ns=now)
                    self._duels[key] = duel
                    self._recent.append(duel)
                duel.add(name, fill)
            cutoff = now - _DUEL_TTL_NS
            for key in [k for k, d in self._duels.items() if d.created_wall_ns < cutoff]:
                del self._duels[key]

    def snapshot(self) -> dict:
        with self._lock:
            both = [d for d in self._recent if DZ in d.sides and PUBLIC in d.sides]
            head_to_head = {
                "n": len(both),
                "dz_only_filled": sum(1 for d in both
                                      if d.sides[DZ].filled and not d.sides[PUBLIC].filled),
                "public_only_filled": sum(1 for d in both
                                          if d.sides[PUBLIC].filled and not d.sides[DZ].filled),
                "both_filled": sum(1 for d in both
                                   if d.sides[DZ].filled and d.sides[PUBLIC].filled),
            }
            return {
                "updated_at": time.time(),
                "uptime_s": round((now_ns() - self.started_ns) / 1e9, 1),
                "mode": "paper",
                "markout_ms": self._markout_ns / 1e6,
                "reaction_ms": self._reaction_ns / 1e6,
                "events": dict(self.counts),
                "scoreboard": {name: board.as_dict() for name, board in self.boards.items()},
                "head_to_head": head_to_head,
                "recent": [d.as_dict() for d in list(self._recent)[-20:]][::-1],
            }


# --- feed adapters -----------------------------------------------------------
# Both feeds are put onto the same (dollars, contracts) axes here, at the edge,
# so nothing downstream has to know which pipe an event came from.

def _dz_reader(state: DemoState, group: str, ports: set[int], link: str,
               stop: threading.Event) -> None:
    group_bytes = bytes(int(x) for x in group.split("."))
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_IP))
    sock.bind((link, 0))
    sock.settimeout(0.5)
    decoder = DzDecoder()
    try:
        while not stop.is_set():
            try:
                data = sock.recv(65535)
            except TimeoutError:
                continue
            if len(data) < 28 or data[9] != 17 or data[16:20] != group_bytes:
                continue
            ihl = (data[0] & 0x0F) * 4
            if ((data[ihl + 2] << 8) | data[ihl + 3]) not in ports:
                continue
            t = now_ns()
            for event in decoder.decode(data[ihl + 8:], t):
                if event.market not in CONTRACT_SIZE:
                    continue
                if event.size is None:
                    continue
                state.on_event(DZ, _rescale_dz(event))
    finally:
        sock.close()


def _rescale_dz(event: Event) -> Event:
    """DZ sizes are in the underlying; the public feed counts contracts. Put the
    DZ side onto contracts so both bots read one threshold the same way."""
    return Event(source=event.source, t_arrival_ns=event.t_arrival_ns,
                 market=event.market, kind=event.kind, price=event.price,
                 size=event.size / CONTRACT_SIZE[event.market], side=event.side,
                 seq=event.seq, exch_ts_ns=event.exch_ts_ns)


async def _public_ws(state: DemoState) -> None:
    cfg = kalshi_prod()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)

    def headers() -> dict:
        return signer.headers("GET", MARGIN_WS_PATH)

    feed = PublicFeed()

    async def on_message(raw) -> None:
        t = now_ns()
        try:
            payload = orjson.loads(raw if isinstance(raw, (bytes, bytearray))
                                   else raw.encode())
        except Exception:  # noqa: BLE001 - non-JSON control frames
            return
        for event in feed.on_message(payload, t):
            state.on_event(PUBLIC, event)

    sub = [{"id": 1, "cmd": "subscribe",
            "params": {"channels": ["trade", "orderbook_delta"],
                       "market_tickers": PERP_TICKERS}}]
    await ReconnectingWS(MARGIN_WS_URL, headers, on_message, subscribe_msgs=sub).run()


def _write_json(path: str, obj: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(orjson.dumps(obj))
    os.replace(tmp, path)


async def _writer(state: DemoState, out_path: str, flush_ms: int) -> None:
    while True:
        state.settle_due()
        _write_json(out_path, state.snapshot())
        await asyncio.sleep(flush_ms / 1000)


async def _main(args: argparse.Namespace) -> None:
    state = DemoState(
        StrategyConfig(min_print_size=args.min_print_size, order_size=args.order_size,
                       max_position=args.max_position,
                       cooldown_ns=int(args.cooldown_s * 1e9)),
        markout_ns=int(args.markout_ms * 1e6),
        reaction_ns=int(args.reaction_ms * 1e6))
    stop = threading.Event()
    reader = threading.Thread(target=_dz_reader, daemon=True, args=(
        state, args.group, {args.mktdata_port, args.refdata_port}, args.link, stop))
    reader.start()
    try:
        await asyncio.gather(_public_ws(state),
                             _writer(state, args.out, args.flush_ms))
    finally:
        stop.set()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", default="233.84.178.3")
    ap.add_argument("--mktdata-port", type=int, default=31000)
    ap.add_argument("--refdata-port", type=int, default=41000)
    ap.add_argument("--link", default="doublezero1",
                    help="Interface NAME to capture the DZ feed on via AF_PACKET")
    ap.add_argument("--out", default="data/demo_state.json")
    ap.add_argument("--flush-ms", type=int, default=500)
    ap.add_argument("--markout-ms", type=float, default=DEFAULT_MARKOUT_NS / 1e6)
    ap.add_argument("--reaction-ms", type=float, default=DEFAULT_REACTION_NS / 1e6,
                    help="Time between deciding and the order reaching the venue. "
                         "Applied identically to both bots; without it the "
                         "DoubleZero bot is judged on the very book snapshot it "
                         "just acted on and fills ~always")
    ap.add_argument("--min-print-size", type=float, default=50.0)
    ap.add_argument("--order-size", type=int, default=1)
    ap.add_argument("--max-position", type=int, default=5)
    ap.add_argument("--cooldown-s", type=float, default=2.0)
    return ap.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    main()
