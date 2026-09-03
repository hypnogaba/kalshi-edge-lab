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

try:  # numpy arrives via matplotlib; the pure-Python path below is equivalent
    import numpy as _np
except ImportError:  # pragma: no cover - exercised by the fallback test
    _np = None

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


_PCT_POINTS = (0.10, 0.50, 0.90, 0.95, 0.99)


def _index_for(p: float, m: int) -> int:
    """The rank this code has always called the p-th percentile."""
    return min(m - 1, int(m * p))


def _summarise(values: list) -> dict | None:
    """Percentiles, extremes and mean over `values`, skipping None.

    numpy is used when importable, and not for speed alone: CPython's sort
    holds the GIL for the whole call, so summarising a full day of samples
    stalls every other thread for tens of milliseconds at a stretch -- and one
    of those threads is where the public feed's arrival gets stamped, which
    would quietly charge our own bookkeeping to the feed we are measuring
    against. np.partition releases the GIL and is O(n) besides.

    Both paths return identical numbers: the same integer ranks, no
    interpolation. `test_numpy_and_pure_python_summaries_agree` holds them to
    that.
    """
    clean = [v for v in values if v is not None]
    m = len(clean)
    if not m:
        return None
    ranks = {p: _index_for(p, m) for p in _PCT_POINTS}

    if _np is not None:
        arr = _np.asarray(clean, dtype=float)
        wanted = sorted({*ranks.values(), 0, m - 1})
        part = _np.partition(arr, wanted)
        pick = {p: float(part[r]) for p, r in ranks.items()}
        lo, hi, mean = float(part[0]), float(part[m - 1]), float(arr.mean())
    else:
        ordered = sorted(clean)
        pick = {p: ordered[r] for p, r in ranks.items()}
        lo, hi, mean = ordered[0], ordered[-1], sum(ordered) / m

    return {"n": m,
            "p10_ms": round(pick[0.10], 3), "p50_ms": round(pick[0.50], 3),
            "p90_ms": round(pick[0.90], 3), "p95_ms": round(pick[0.95], 3),
            "p99_ms": round(pick[0.99], 3),
            "avg_ms": round(mean, 3),
            "min_ms": round(lo, 3), "max_ms": round(hi, 3)}


def _match_key(market: str, dollars: float, contracts: float, exch_ms: int) -> tuple:
    return (market, exch_ms, round(dollars), round(contracts))


# A trade cannot reach us before the venue stamped it, and nothing on this
# route has ever honestly taken half a second. Outside this band the wall
# clock moved, not the packet.
_MIN_PLAUSIBLE_MS = 0.0
_MAX_PLAUSIBLE_MS = 5_000.0

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
        # Samples land in the HOT deques, which the feed threads append to under
        # the lock, and are drained into the WIN deques, which only snapshot()
        # touches and which therefore need no lock at all. Draining is a pointer
        # swap, so the time a feed thread can wait behind a flush no longer
        # grows with the window: at a full day it was ~0.2 s per flush just to
        # copy, and a stalled event loop is charged to the public feed as
        # latency -- the measurement would have been inflating its own result.
        self._deltas_hot: deque[tuple[int, float]] = deque()  # (mono_ns, delta_ms)
        self._deltas_win: deque[tuple[int, float]] = deque()
        # Absolute legs, recorded only on MATCHED pairs so the DoubleZero and
        # public numbers describe the identical set of trades. Each entry:
        # (mono_ns, dz_total_ms, pub_total_ms, dz_transport_ms|None,
        #  exch_to_pub_ms|None)
        self._abs_hot: deque[tuple[int, float, float, float | None, float | None]] = deque()
        self._abs_win: deque[tuple[int, float, float, float | None, float | None]] = deque()
        self._window_ns = int(window_min * 60 * 1e9)
        self.dz_seen = 0
        self.pub_seen = 0
        self.matched = 0
        # Samples rejected as clock artefacts; surfaced so a silent
        # drop can never be mistaken for a clean measurement.
        self.implausible = 0
        # Matches per market, so "all perps" can be checked rather than claimed.
        self.matched_by_market: Counter[str] = Counter()

    def _record(self, key: tuple, dz: "Half", pub: "Half") -> None:
        now = now_ns()
        self._deltas_hot.append((now, (dz.mono_ns - pub.mono_ns) / 1e6))
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
        # A wall clock can be stepped -- by chrony after a long outage, by a
        # hypervisor resuming a paused guest. One stepped sample would sit in
        # the window for a full day and own the max and the 99th percentile,
        # so anything physically impossible is dropped and counted instead.
        # Nothing legitimate is near these bounds: the floor for this route is
        # ~43 ms and the worst honest sample seen is under half a second.
        if not (_MIN_PLAUSIBLE_MS <= dz_total <= _MAX_PLAUSIBLE_MS
                and _MIN_PLAUSIBLE_MS <= pub_total <= _MAX_PLAUSIBLE_MS):
            self.implausible += 1
            return
        transport = exch_to_pub = None
        if dz.pub_ts_ns:
            transport = (dz.wall_ns - dz.pub_ts_ns) / 1e6
            exch_to_pub = (dz.pub_ts_ns - dz.exch_ts_ns) / 1e6
        self._abs_hot.append((now, dz_total, pub_total, transport, exch_to_pub))

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

    def _expire_pending(self, now: int) -> None:
        """Drop half-trades whose twin never arrived. Caller holds the lock;
        this is bounded by the number of unmatched halves, not by the window."""
        ttl = now - _KEY_TTL_NS
        for d in (self._dz, self._pub):
            for k in [k for k, v in d.items() if v.mono_ns < ttl]:
                del d[k]

    def _age_out(self, now: int) -> None:
        """Drop samples that fell out of the rolling window. Lock-free: only
        snapshot() ever touches the WIN deques."""
        cutoff = now - self._window_ns
        while self._deltas_win and self._deltas_win[0][0] < cutoff:
            self._deltas_win.popleft()
        while self._abs_win and self._abs_win[0][0] < cutoff:
            self._abs_win.popleft()

    def snapshot(self, window_min: float) -> dict:
        """Summarise the window. Copies under the lock, computes outside it.

        Sorting a day of samples takes ~800 ms at a full 24h window, and
        holding the lock across that stalls both feed threads. The DoubleZero
        arrival stamp comes from the kernel and survives a stall, but the
        public WebSocket is stamped in `on_message`, so a stalled event loop
        is charged to the public feed as latency -- the measurement would have
        been inflating the very gap it exists to report. So: take copies while
        locked, then do every sort, percentile and subprocess call unlocked.
        """
        now = now_ns()
        with self._lock:
            # Two pointer swaps and a bounded sweep: everything else waits.
            hot_deltas, self._deltas_hot = self._deltas_hot, deque()
            hot_abs, self._abs_hot = self._abs_hot, deque()
            self._expire_pending(now)
            counters = (self.dz_seen, self.pub_seen, self.matched,
                        self.implausible, len(self.matched_by_market),
                        dict(self.matched_by_market.most_common(20)))

        self._deltas_win.extend(hot_deltas)
        self._abs_win.extend(hot_abs)
        self._age_out(now)
        deltas = [d for _, d in self._deltas_win]
        abs_rows = list(self._abs_win)
        recent = [{"d": round(d, 2), "w": d < 0}
                  for _, d in list(self._deltas_win)[-90:]]

        dz_seen, pub_seen, matched, implausible, market_count, by_market = counters
        n = len(deltas)
        summary = _summarise(deltas)
        out = {
            "updated_at": time.time(),
            "window_min": window_min,
            "n": n,
            "dz_seen": dz_seen,
            "pub_seen": pub_seen,
            "matched_total": matched,
            "implausible_dropped": implausible,
            "matched_markets": market_count,
            "matched_by_market": by_market,
        }
        if summary:
            if _np is not None:
                wins = int((_np.asarray(deltas, dtype=float) < 0).sum())
            else:
                wins = sum(1 for d in deltas if d < 0)
            out.update({
                "p10_ms": summary["p10_ms"], "p50_ms": summary["p50_ms"],
                "p90_ms": summary["p90_ms"], "p95_ms": summary["p95_ms"],
                "min_ms": summary["min_ms"], "max_ms": summary["max_ms"],
                # win_rate: % of matched trades DoubleZero delivered first
                "win_rate": round(100.0 * wins / n, 1),
                # median milliseconds sooner (positive number for the UI)
                "sooner_p50_ms": round(-summary["p50_ms"], 3),
            })
        out["absolute"] = self._absolute_block(abs_rows)
        # Last matched trades in arrival order, for the live win-strip:
        # d = delta ms (dz-public), w = DoubleZero arrived first.
        out["recent"] = recent
        return out

    @staticmethod
    def _absolute_block(rows: list) -> dict:
        """End-to-end time from the venue's own stamp to this host, per feed.

        Takes an already-copied list so it can run without the lock: it sorts
        four series and shells out to chrony, none of which a feed thread
        should ever wait behind.
        """
        n = len(rows)
        block: dict = {"n": n, "clock": clock_offset_ms()}
        if not n:
            return block

        block["dz_total"] = _summarise([r[1] for r in rows])
        block["public_total"] = _summarise([r[2] for r in rows])
        block["dz_transport"] = _summarise([r[3] for r in rows])
        block["exch_to_pub"] = _summarise([r[4] for r in rows])
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
    def build_and_write() -> None:
        _write_json(out_path, {**meta, **state.snapshot(window_min)})

    while True:
        # snapshot() sorts the whole window. Run on the event loop it blocks
        # the public WebSocket handler, and since that handler is where the
        # public feed's arrival is stamped, the delay is charged to the public
        # feed as latency -- the flush would be widening the very gap it
        # reports. Off the loop it goes, together with the write.
        await asyncio.to_thread(build_and_write)
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
