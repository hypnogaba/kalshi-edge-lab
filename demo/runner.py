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
from collections.abc import Callable
from dataclasses import dataclass, field

import orjson

from common.clock import now_ns
from common.config import kalshi_prod
from common.event import Event, Kind
from common.ws_client import ReconnectingWS
from demo.fills import DEFAULT_MARKOUT_NS, DEFAULT_REACTION_NS, Fill, GroundTruth, Scoreboard
from demo.public_feed import PublicFeed
from demo.strategy import FollowThePrint, Intent, StrategyConfig
from sources.dz_feed.arms import ArmArbiter
from sources.dz_feed.contract_sizes import ContractSizes
from sources.dz_feed.decoder import DzDecoder, frame_channel
from sources.kalshi_ws.auth import KalshiSigner

_log = logging.getLogger(__name__)

MARGIN_WS_URL = "wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin"
MARGIN_WS_PATH = "/trade-api/ws/v2/margin"
_ETH_P_IP = 0x0800
_DUEL_TTL_NS = 30 * 1_000_000_000
DEFAULT_WINDOW_MIN = 360.0  # rolling window for the headline numbers

# The DZ feed reports trade size in the underlying, the public feed counts
# contracts. The ratio is the market's contract size, and it differs per market
# (BTC 1e-4, DOGE 100). It is NOT hard-coded here: the feed's own instrument
# definitions carry it as lot_size, which was checked against the ratio measured
# on live matched BTC trades. See sources/dz_feed/registry.py.
PERP_TICKERS = [
    "KXBTCPERP", "KXETHPERP", "KXSOLPERP", "KXXRPPERP", "KXBCHPERP", "KXDOGEPERP",
    "KXHYPEPERP", "KXKSHIBPERP", "KXLINKPERP", "KXLTCPERP", "KXNEARPERP",
    "KXSUIPERP", "KXZECPERP",
]

DZ = "doublezero"
PUBLIC = "public"


def duel_key(market: str, dollars: float, contracts: float, exch_ts_ns: int,
             tick: float) -> tuple:
    """Same join key as the latency race: the venue's own view of one trade,
    with the price counted in the market's own ticks so a cheap market keeps
    its price in the key (see sources/dz_feed/contract_sizes.py)."""
    return (market, exch_ts_ns // 1_000_000, round(dollars / tick), round(contracts))


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
                 reaction_ns: int = DEFAULT_REACTION_NS,
                 window_min: float = DEFAULT_WINDOW_MIN, *,
                 tick_of: Callable[[str], float | None]) -> None:
        self._lock = threading.Lock()
        # Both bots' decisions are paired on the print they reacted to, and the
        # key quantises the price by the market's own tick. It comes from the DZ
        # reference data, which is also what puts the two feeds on one axis, so
        # an event that got this far always has one.
        #
        # Required, and keyword-only, deliberately. Defaulting it to "no ticks
        # known" costs nothing at startup and then silently pairs NOTHING: every
        # duel is dropped, both fill rates read 0, and the demo looks quiet
        # rather than broken. A missing argument should stop the process, not
        # empty the scoreboard.
        self._tick_of = tick_of
        self._markout_ns = markout_ns
        self._reaction_ns = reaction_ns
        self._window_ns = int(window_min * 60 * 1e9)
        self._window_min = window_min
        # (wall_ns, dz_filled, public_filled, lead_ms) for duels both bots acted
        # on. Lifetime totals live in the scoreboards; this is what the headline
        # quotes, so a demo that has been up for days still shows today.
        self._settled: deque[tuple[int, bool, bool, float]] = deque()
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
                tick = self._tick_of(event.market)
                if tick is None or tick <= 0:
                    return  # no reference data: a key here could not pair anyway
                key = duel_key(event.market, event.price, event.size,
                               event.exch_ts_ns, tick)
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
                if DZ in duel.sides and PUBLIC in duel.sides:
                    dz_fill, pub_fill = duel.sides[DZ], duel.sides[PUBLIC]
                    lead_ms = (pub_fill.intent.t_decided_ns
                               - dz_fill.intent.t_decided_ns) / 1e6
                    self._settled.append((now, dz_fill.filled, pub_fill.filled, lead_ms))
            window_start = now - self._window_ns
            while self._settled and self._settled[0][0] < window_start:
                self._settled.popleft()
            cutoff = now - _DUEL_TTL_NS
            for key in [k for k, d in self._duels.items() if d.created_wall_ns < cutoff]:
                del self._duels[key]

    def snapshot(self) -> dict:
        with self._lock:
            settled = list(self._settled)
            n = len(settled)
            leads = sorted(lead for _, _, _, lead in settled)
            head_to_head = {
                "window_min": self._window_min,
                "n": n,
                "dz_only_filled": sum(1 for _, dz, pub, _ in settled if dz and not pub),
                "public_only_filled": sum(1 for _, dz, pub, _ in settled if pub and not dz),
                "both_filled": sum(1 for _, dz, pub, _ in settled if dz and pub),
                "neither_filled": sum(1 for _, dz, pub, _ in settled if not dz and not pub),
                "dz_fill_rate": round(100.0 * sum(1 for _, dz, _, _ in settled if dz) / n, 1)
                                 if n else None,
                "public_fill_rate": round(100.0 * sum(1 for _, _, pub, _ in settled if pub) / n, 1)
                                    if n else None,
                "median_lead_ms": round(leads[n // 2], 3) if n else None,
            }
            return {
                "updated_at": time.time(),
                "uptime_s": round((now_ns() - self.started_ns) / 1e9, 1),
                "mode": "paper",
                "markets": PERP_TICKERS,
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
               sizes: ContractSizes, arbiter: ArmArbiter,
               stop: threading.Event) -> None:
    group_bytes = bytes(int(x) for x in group.split("."))
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_IP))
    sock.bind((link, 0))
    sock.settimeout(0.5)
    decoder = DzDecoder()
    wanted = set(PERP_TICKERS)
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
            payload = data[ihl + 8:]
            channel = frame_channel(payload)
            if channel is None:
                continue
            arbiter.note_frame(channel, t)
            events = decoder.decode(payload, t)
            # The group carries two publisher arms. Both are offered to the
            # arbiter, so it can see which one leads, and only the winner's
            # events reach the bot: the loser's copies land ~5 ms late and, on
            # quotes, walk the DoubleZero bot's book backwards -- which is the
            # one thing this demo must not do.
            for event in events:
                if event.kind is Kind.TRADE and event.size is not None:
                    arbiter.observe_trade(channel, (event.market, event.price,
                                                    event.size), t)
            if not arbiter.accepts(channel, t):
                continue
            for event in events:
                if event.size is None or event.market not in wanted:
                    continue
                # Reference data arrives on the refdata port within seconds of
                # joining. Until a market's contract size is known, neither feed
                # can be put on a common axis, so it is skipped, not guessed.
                contract_size = sizes.learn_from(decoder.registry, event.market)
                if contract_size is None:
                    continue
                state.on_event(DZ, _rescale_dz(event, contract_size))
    finally:
        sock.close()


def _rescale_dz(event: Event, contract_size: float) -> Event:
    """DZ sizes are in the underlying; the public feed counts contracts. Put the
    DZ side onto contracts so both bots read one threshold the same way."""
    return Event(source=event.source, t_arrival_ns=event.t_arrival_ns,
                 market=event.market, kind=event.kind, price=event.price,
                 size=event.size / contract_size, side=event.side,
                 seq=event.seq, exch_ts_ns=event.exch_ts_ns)


async def _public_ws(state: DemoState, sizes: ContractSizes) -> None:
    cfg = kalshi_prod()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)

    def headers() -> dict:
        return signer.headers("GET", MARGIN_WS_PATH)

    feed = PublicFeed(sizes.get)

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


async def _writer(state: DemoState, arbiter: ArmArbiter, out_path: str,
                  flush_ms: int) -> None:
    while True:
        state.settle_due()
        _write_json(out_path, {**state.snapshot(), "arms": arbiter.stats(now_ns())})
        await asyncio.sleep(flush_ms / 1000)


async def _main(args: argparse.Namespace) -> None:
    sizes = ContractSizes()
    state = DemoState(
        StrategyConfig(min_print_size=args.min_print_size, order_size=args.order_size,
                       max_position=args.max_position,
                       cooldown_ns=int(args.cooldown_s * 1e9)),
        markout_ns=int(args.markout_ms * 1e6),
        reaction_ns=int(args.reaction_ms * 1e6),
        tick_of=sizes.tick)
    stop = threading.Event()
    arbiter = ArmArbiter(args.dz_channel)
    reader = threading.Thread(target=_dz_reader, daemon=True, args=(
        state, args.group, {args.mktdata_port, args.refdata_port}, args.link,
        sizes, arbiter, stop))
    reader.start()
    try:
        await asyncio.gather(_public_ws(state, sizes),
                             _writer(state, arbiter, args.out, args.flush_ms))
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
    ap.add_argument("--dz-channel", type=int, default=None,
                    help="Force a DZ frame Channel ID instead of arbitrating the "
                         "publisher arms automatically (see sources/dz_feed/arms.py)")
    return ap.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    main()
