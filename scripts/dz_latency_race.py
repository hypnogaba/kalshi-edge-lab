"""Live latency race: DoubleZero edge feed vs Kalshi public perps WS -> data/dz_latency.json.

Both sides run on ONE host with ONE clock (common.clock.now_ns), so the arrival
delta is fair (no cross-machine skew). The SAME trade is matched across the two
feeds by (exchange-timestamp-ms, price, contract-count) -- Kalshi's public
`trade_id` (a UUID) and the DZ feed's trade id (a u64) are different id spaces,
but every trade carries the venue's own execution timestamp + price + size,
which is identical on both feeds. Delta = t_arrival(dz) - t_arrival(public);
negative => DoubleZero delivered it first.

Public side: Kalshi margin/perps WS `wss://external-api-margin-ws.kalshi.com/...`
(API-key auth at handshake; the `trade` channel is public). DZ side: multicast
Top-of-Book & Trades over doublezero1, read via AF_PACKET (a UDP socket receives
nothing on the tunnel -- see sources/dz_feed/capture.py).

Writes a rolling-window latency summary (p50/p90/win-rate over the last
--window-min minutes) every --flush-ms for the web dashboard.

Run (needs CAP_NET_RAW for AF_PACKET + a Kalshi PROD key in .env):
  sudo .venv/bin/python -m scripts.dz_latency_race --ticker KXBTCPERP
"""
import argparse
import asyncio
import contextlib
import logging
import os
import socket
import struct
import threading
import time
from collections import Counter, deque

import orjson

from dataclasses import dataclass

from common.clock import clock_offset_ms, now_ns, wall_ns
from common.config import kalshi_prod
from common.event import Kind
from common.ws_client import ReconnectingWS
from sources.dz_feed.contract_sizes import ContractSizes
from sources.dz_feed.decoder import DzDecoder
from sources.kalshi_ws.auth import KalshiSigner

_log = logging.getLogger(__name__)

MARGIN_WS_URL = "wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin"
MARGIN_WS_PATH = "/trade-api/ws/v2/margin"
# The two feeds report the same trade on different axes: the public side quotes
# dollars per CONTRACT and counts contracts, the DZ side quotes dollars per unit
# of underlying and sizes in the underlying. Both are converted with that
# market's own contract size, which the DZ feed publishes as lot_size -- see
# sources/dz_feed/contract_sizes.py.
#
# This used to be a flat 1e4 / 1e-4 on both sides. That is right for KXBTCPERP
# alone, whose contract happens to be 1e-4: on KXETHPERP (contract 1e-3) the
# same $2,393.8 trade keyed as $23,938 on one side and $2,394 on the other, so
# it never matched. The race was reporting "all Kalshi crypto perpetuals" while
# in practice matching BTC only.
_ETH_P_IP = 0x0800
_KEY_TTL_NS = 30 * 1_000_000_000  # drop an unmatched half-trade after 30s

# Kernel packet timestamping. Taking the arrival stamp in userspace after
# recv() returns charges our own scheduling delay to the network (measured on
# this host: p50 0.31 ms, p90 1.02 ms, tail to 23 ms under load). SO_TIMESTAMPNS
# hands us the time the kernel took the packet off the interface instead, which
# is what an absolute latency figure has to be measured from.
_SO_TIMESTAMPNS = 35
_SCM_TIMESTAMPNS = 35
_TIMESPEC = struct.Struct("qq")

# All Kalshi crypto perpetuals — race across every one, so the scoreboard stays
# populated even when a single market (e.g. BTC) is quiet.
PERP_TICKERS = [
    "KXBTCPERP", "KXETHPERP", "KXSOLPERP", "KXXRPPERP", "KXBCHPERP", "KXDOGEPERP",
    "KXHYPEPERP", "KXKSHIBPERP", "KXLINKPERP", "KXLTCPERP", "KXNEARPERP",
    "KXSUIPERP", "KXZECPERP",
]


def _match_key(market: str, dollars: float, contracts: float, exch_ms: int) -> tuple:
    return (market, exch_ms, round(dollars), round(contracts))


_HIST_LO_MS = 45.0
_HIST_HI_MS = 95.0
_HIST_BINS = 50


def _histogram(dz: list[float], public: list[float]) -> dict:
    """Both feeds binned on ONE shared axis, so the two shapes are comparable.

    A median says where the middle sits; the shape says whether the two paths
    are actually separate populations or merely different averages of the same
    one. Values past the top of the axis are counted, not dropped, so a heavy
    tail cannot be hidden by the choice of range.
    """
    width = (_HIST_HI_MS - _HIST_LO_MS) / _HIST_BINS

    def bin_them(vals: list[float]) -> tuple[list[int], int, int]:
        bins = [0] * _HIST_BINS
        under = over = 0
        for v in vals:
            if v is None:
                continue
            if v < _HIST_LO_MS:
                under += 1
            elif v >= _HIST_HI_MS:
                over += 1
            else:
                bins[int((v - _HIST_LO_MS) / width)] += 1
        return bins, under, over

    dz_bins, dz_under, dz_over = bin_them(dz)
    pub_bins, pub_under, pub_over = bin_them(public)
    return {
        "lo_ms": _HIST_LO_MS, "hi_ms": _HIST_HI_MS, "width_ms": round(width, 4),
        "dz": dz_bins, "dz_under": dz_under, "dz_over": dz_over,
        "public": pub_bins, "public_under": pub_under, "public_over": pub_over,
    }


@dataclass(frozen=True, slots=True)
class Half:
    """One feed's sighting of a trade, before its twin on the other feed shows up.

    `mono_ns` is the monotonic stamp: the only one valid for the feed-vs-feed
    delta. `wall_ns` is the realtime stamp, valid against the venue's own
    `exch_ts_ns` and therefore the basis of every absolute figure.
    """
    mono_ns: int
    wall_ns: int
    exch_ts_ns: int | None = None
    pub_ts_ns: int | None = None


class RaceState:
    """Cross-thread trade matcher + rolling-window latency stats."""

    def __init__(self, window_min: float) -> None:
        self._lock = threading.Lock()
        # key -> Half(...) for the side that arrived first and is still waiting
        # for its twin on the other feed.
        self._dz: dict[tuple, Half] = {}
        self._pub: dict[tuple, Half] = {}
        self._deltas: deque[tuple[int, float]] = deque()  # (mono_ns, delta_ms)
        # Absolute legs, recorded only on MATCHED pairs so the DoubleZero and
        # public numbers describe the identical set of trades. Each entry:
        # (mono_ns, dz_total_ms, pub_total_ms, dz_transport_ms|None,
        #  exch_to_pub_ms|None)
        self._abs: deque[tuple[int, float, float, float | None, float | None]] = deque()
        self._window_ns = int(window_min * 60 * 1e9)
        self.dz_seen = 0
        self.pub_seen = 0
        self.matched = 0
        # Matches per market, so "all perps" can be checked rather than claimed.
        self.matched_by_market: Counter[str] = Counter()

    def _record(self, key: tuple, dz: "Half", pub: "Half") -> None:
        now = now_ns()
        self._deltas.append((now, (dz.mono_ns - pub.mono_ns) / 1e6))
        self.matched += 1
        self.matched_by_market[key[0]] += 1

        # Absolute latency needs the venue's own stamp on both sides. The
        # public feed publishes it at millisecond resolution, so both sides are
        # truncated to the same millisecond by the match key; that truncation
        # biases every total UP by up to 1 ms (mean ~0.5 ms), never down.
        if not (dz.exch_ts_ns and pub.exch_ts_ns):
            return
        dz_total = (dz.wall_ns - dz.exch_ts_ns) / 1e6
        pub_total = (pub.wall_ns - pub.exch_ts_ns) / 1e6
        transport = exch_to_pub = None
        if dz.pub_ts_ns:
            transport = (dz.wall_ns - dz.pub_ts_ns) / 1e6
            exch_to_pub = (dz.pub_ts_ns - dz.exch_ts_ns) / 1e6
        self._abs.append((now, dz_total, pub_total, transport, exch_to_pub))

    def add_dz(self, key: tuple, half: "Half") -> None:
        with self._lock:
            self.dz_seen += 1
            other = self._pub.pop(key, None)
            if other is not None:
                self._record(key, half, other)
            else:
                self._dz[key] = half

    def add_pub(self, key: tuple, half: "Half") -> None:
        with self._lock:
            self.pub_seen += 1
            other = self._dz.pop(key, None)
            if other is not None:
                self._record(key, other, half)
            else:
                self._pub[key] = half

    def _evict(self, now: int) -> None:
        cutoff = now - self._window_ns
        while self._deltas and self._deltas[0][0] < cutoff:
            self._deltas.popleft()
        while self._abs and self._abs[0][0] < cutoff:
            self._abs.popleft()
        ttl = now - _KEY_TTL_NS
        for d in (self._dz, self._pub):
            for k in [k for k, v in d.items() if v.mono_ns < ttl]:
                del d[k]

    def snapshot(self, window_min: float) -> dict:
        with self._lock:
            now = now_ns()
            self._evict(now)
            deltas = sorted(d for _, d in self._deltas)
            n = len(deltas)
            out = {
                "updated_at": time.time(),
                "window_min": window_min,
                "n": n,
                "dz_seen": self.dz_seen,
                "pub_seen": self.pub_seen,
                "matched_total": self.matched,
                "matched_markets": len(self.matched_by_market),
                "matched_by_market": dict(self.matched_by_market.most_common(20)),
            }
            if n:
                def pct(p: float) -> float:
                    return round(deltas[min(n - 1, int(n * p))], 3)
                wins = sum(1 for d in deltas if d < 0)
                out.update({
                    "p10_ms": pct(0.10), "p50_ms": pct(0.50),
                    "p90_ms": pct(0.90), "p95_ms": pct(0.95),
                    "min_ms": round(deltas[0], 3), "max_ms": round(deltas[-1], 3),
                    # win_rate: % of matched trades DoubleZero delivered first
                    "win_rate": round(100.0 * wins / n, 1),
                    # median milliseconds sooner (positive number for the UI)
                    "sooner_p50_ms": round(-pct(0.50), 3),
                })
            out["absolute"] = self._absolute_block()
            # Last matched trades in arrival order, for the live win-strip:
            # d = delta ms (dz-public), w = DoubleZero arrived first.
            out["recent"] = [{"d": round(d, 2), "w": d < 0}
                             for _, d in list(self._deltas)[-90:]]
            return out

    def _absolute_block(self) -> dict:
        """End-to-end time from the venue's own stamp to this host, per feed.

        Unlike the head-to-head delta this leans on wall clocks, so it ships
        with the clock quality that produced it. Callers must hold the lock.
        """
        n = len(self._abs)
        block: dict = {"n": n, "clock": clock_offset_ms()}
        if not n:
            return block

        def pcts(vals: list[float]) -> dict | None:
            vals = sorted(v for v in vals if v is not None)
            if not vals:
                return None
            m = len(vals)

            def at(p: float) -> float:
                return round(vals[min(m - 1, int(m * p))], 3)

            # P50/P90/P95/P99 are the percentiles DoubleZero's own scoreboard
            # reports, and the tail is the half of a latency figure that a
            # median alone hides.
            return {"n": m, "p10_ms": at(0.10), "p50_ms": at(0.50),
                    "p90_ms": at(0.90), "p95_ms": at(0.95), "p99_ms": at(0.99),
                    "avg_ms": round(sum(vals) / m, 3),
                    "min_ms": round(vals[0], 3), "max_ms": round(vals[-1], 3)}

        rows = list(self._abs)
        block["dz_total"] = pcts([r[1] for r in rows])
        block["public_total"] = pcts([r[2] for r in rows])
        block["dz_transport"] = pcts([r[3] for r in rows])
        block["exch_to_pub"] = pcts([r[4] for r in rows])
        block["hist"] = _histogram([r[1] for r in rows], [r[2] for r in rows])
        return block


def _dz_reader(state: RaceState, group: str, ports: set[int], link: str,
               sizes: ContractSizes, stop: threading.Event) -> None:
    group_bytes = bytes(int(x) for x in group.split("."))
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_IP))
    sock.bind((link, 0))
    sock.settimeout(0.5)
    kernel_ts = True
    try:
        sock.setsockopt(socket.SOL_SOCKET, _SO_TIMESTAMPNS, 1)
    except OSError:
        kernel_ts = False
        _log.warning("SO_TIMESTAMPNS unavailable; absolute latency will include "
                     "this process's own scheduling delay")
    ancsize = socket.CMSG_SPACE(_TIMESPEC.size)
    decoder = DzDecoder()
    try:
        while not stop.is_set():
            try:
                if kernel_ts:
                    data, anc, _flags, _addr = sock.recvmsg(65535, ancsize)
                else:
                    data, anc = sock.recv(65535), ()
            except TimeoutError:
                continue
            t = now_ns()
            t_wall = 0
            for level, ctype, cdata in anc:
                if level == socket.SOL_SOCKET and ctype == _SCM_TIMESTAMPNS:
                    sec, nsec = _TIMESPEC.unpack(cdata[:_TIMESPEC.size])
                    t_wall = sec * 1_000_000_000 + nsec
            if not t_wall:
                t_wall = wall_ns()
            if len(data) < 28 or data[9] != 17 or data[16:20] != group_bytes:
                continue
            ihl = (data[0] & 0x0F) * 4
            dport = (data[ihl + 2] << 8) | data[ihl + 3]
            if dport not in ports:
                continue
            for e in decoder.decode(data[ihl + 8:], t):
                if not (e.kind == Kind.TRADE and e.exch_ts_ns and e.size is not None
                        and isinstance(e.market, str) and e.market.endswith("PERP")):
                    continue
                contract_size = sizes.learn_from(decoder.registry, e.market)
                if contract_size is None:
                    continue  # reference data has not arrived for this market yet
                key = _match_key(e.market, e.price, e.size / contract_size,
                                 e.exch_ts_ns // 1_000_000)
                state.add_dz(key, Half(mono_ns=t, wall_ns=t_wall,
                                       exch_ts_ns=e.exch_ts_ns,
                                       pub_ts_ns=e.pub_ts_ns))
    finally:
        sock.close()


async def _public_ws(state: RaceState, sizes: ContractSizes) -> None:
    cfg = kalshi_prod()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)

    def headers() -> dict:
        return signer.headers("GET", MARGIN_WS_PATH)

    async def on_message(raw) -> None:
        t = now_ns()
        t_wall = wall_ns()
        try:
            m = orjson.loads(raw if isinstance(raw, (bytes, bytearray)) else raw.encode())
        except Exception:  # noqa: BLE001 - ignore non-JSON control frames
            return
        if m.get("type") != "trade":
            return
        msg = m["msg"]
        contract_size = sizes.get(msg["market_ticker"])
        if contract_size is None:
            return  # not yet on a common axis with the DZ side; it could not match
        exch_ms = int(msg["ts_ms"])
        key = _match_key(msg["market_ticker"], float(msg["price"]) / contract_size,
                         float(msg["count"]), exch_ms)
        state.add_pub(key, Half(mono_ns=t, wall_ns=t_wall,
                                exch_ts_ns=exch_ms * 1_000_000))

    sub = [{"id": 1, "cmd": "subscribe",
            "params": {"channels": ["trade"], "market_tickers": PERP_TICKERS}}]
    client = ReconnectingWS(MARGIN_WS_URL, headers, on_message, subscribe_msgs=sub)
    await client.run()


def _write_json(path: str, obj: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(orjson.dumps(obj))
    os.replace(tmp, path)


async def _flush_loop(state: RaceState, out_path: str, flush_ms: int,
                      window_min: float, meta: dict) -> None:
    while True:
        snap = {**meta, **state.snapshot(window_min)}
        await asyncio.to_thread(_write_json, out_path, snap)
        await asyncio.sleep(flush_ms / 1000.0)


async def _main(args: argparse.Namespace) -> None:
    state = RaceState(args.window_min)
    meta = {
        "ticker": "all perps",
        "markets": len(PERP_TICKERS),
        "dz_group": args.group,
        "public_ws": "external-api-margin-ws.kalshi.com",
        "method": "one host, one clock; match by exch-ts+price+size; delta=dz-public",
        "absolute_method": (
            "end-to-end = kernel packet timestamp (SO_TIMESTAMPNS) minus the "
            "venue's own exchange timestamp, over matched pairs only so both "
            "feeds describe the same trades; exchange stamps are "
            "millisecond-resolution, which biases every total up by <1 ms"
        ),
    }
    sizes = ContractSizes()
    stop = threading.Event()
    reader = threading.Thread(
        target=_dz_reader,
        args=(state, args.group, {args.mktdata_port, args.refdata_port}, args.link,
              sizes, stop),
        daemon=True,
    )
    reader.start()
    _log.info("latency race: all Kalshi perps, DZ %s vs public margin WS", args.group)
    try:
        await asyncio.gather(
            _public_ws(state, sizes),
            _flush_loop(state, args.out, args.flush_ms, args.window_min, meta),
        )
    finally:
        stop.set()
        reader.join(timeout=2)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--link", default="doublezero1")
    ap.add_argument("--group", default="233.84.178.3")
    ap.add_argument("--mktdata-port", type=int, default=31000)
    ap.add_argument("--refdata-port", type=int, default=41000)
    ap.add_argument("--out", default="data/dz_latency.json")
    ap.add_argument("--flush-ms", type=int, default=1000)
    ap.add_argument("--window-min", type=float, default=1440.0)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    try:
        import uvloop  # type: ignore
        uvloop.install()
    except Exception:  # noqa: BLE001, S110 - uvloop optional
        pass
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main(args))


if __name__ == "__main__":
    main()
