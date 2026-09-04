"""Live DoubleZero Kalshi-perps feed reader -> data/dz_feed_state.json.

Runs on the DZ-connected host. Taps the tunnel interface via AF_PACKET (a normal
UDP multicast socket receives nothing on doublezero1 -- see
sources/dz_feed/capture.py), decodes the Top-of-Book & Trades v3 frames with the
same DzDecoder used by the race, and keeps a live per-market snapshot
(best bid/ask + last trade + counts). Every --flush-ms it atomically writes a
compact JSON the web dashboard renders.

This powers the "live feed" showcase: the Kalshi crypto perpetuals carried here
(KXBTCPERP, KXETHPERP, ...) are NOT exposed on Kalshi's public API, so this is
data you can only get over the DoubleZero edge feed.

Run:
  sudo .venv/bin/python -m scripts.dz_live_feed \
    --link doublezero1 --group 233.84.178.3 --mktdata-port 31000 \
    --refdata-port 41000 --out data/dz_feed_state.json
"""
import argparse
import logging
import os
import select
import socket
import time
from socket import inet_aton

import orjson

from common.clock import now_ns
from common.event import Kind, Side
from sources.dz_feed.arms import ArmArbiter
from sources.dz_feed.decoder import DzDecoder, frame_channel

_log = logging.getLogger(__name__)

_ETH_P_IP = 0x0800
_IPPROTO_UDP = 17
_RECV_BUFSIZE = 65535


def _open_afpacket(link_ifname: str) -> socket.socket:
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_IP))
    sock.bind((link_ifname, 0))
    sock.setblocking(False)
    return sock


def _udp_payload(data: bytes, group_bytes: bytes, ports: set[int]) -> bytes | None:
    """Return the UDP payload if `data` (an IPv4 packet) is UDP to `group` on a
    wanted port, else None."""
    if len(data) < 20 or data[9] != _IPPROTO_UDP or data[16:20] != group_bytes:
        return None
    ihl = (data[0] & 0x0F) * 4
    if len(data) < ihl + 8:
        return None
    dport = (data[ihl + 2] << 8) | data[ihl + 3]
    if dport not in ports:
        return None
    return data[ihl + 8:]


class LiveState:
    """Per-market top-of-book + last trade + counts, plus feed-wide totals/rates."""

    def __init__(self) -> None:
        self.markets: dict[str, dict] = {}
        self.frames = 0
        self.quotes = 0
        self.trades = 0
        self.started_ns = now_ns()
        # rolling window for rates
        self._win_start_ns = self.started_ns
        self._win_frames = 0
        self._win_trades = 0
        self.msgs_per_s = 0.0
        self.trades_per_s = 0.0

    def _mkt(self, symbol: str) -> dict:
        m = self.markets.get(symbol)
        if m is None:
            m = {"bid": None, "ask": None, "bid_size": None, "ask_size": None,
                 "last_price": None, "last_size": None, "last_side": None,
                 "last_trade_ns": None, "trades": 0, "quotes": 0}
            self.markets[symbol] = m
        return m

    def apply(self, events) -> None:
        for e in events:
            symbol = e.market if isinstance(e.market, str) else str(e.market)
            m = self._mkt(symbol)
            if e.kind == Kind.QUOTE:
                self.quotes += 1
                m["quotes"] += 1
                if e.side == Side.BID:
                    m["bid"], m["bid_size"] = e.price, e.size
                elif e.side == Side.ASK:
                    m["ask"], m["ask_size"] = e.price, e.size
            elif e.kind == Kind.TRADE:
                self.trades += 1
                self._win_trades += 1
                m["trades"] += 1
                m["last_price"], m["last_size"] = e.price, e.size
                m["last_side"] = e.side.value if e.side else None
                m["last_trade_ns"] = e.t_arrival_ns

    def tick_rates(self) -> None:
        now = now_ns()
        dt = (now - self._win_start_ns) / 1e9
        if dt >= 1.0:
            self.msgs_per_s = self._win_frames / dt
            self.trades_per_s = self._win_trades / dt
            self._win_start_ns = now
            self._win_frames = 0
            self._win_trades = 0

    def snapshot(self, meta: dict, arms: dict | None = None) -> dict:
        now = now_ns()
        # Only surface markets that actually resolved to a Kalshi symbol.
        markets = {k: v for k, v in self.markets.items() if k.startswith("KX")}
        return {
            **meta,
            "updated_at": time.time(),
            "uptime_s": round((now - self.started_ns) / 1e9, 1),
            "totals": {"frames": self.frames, "quotes": self.quotes, "trades": self.trades},
            "rates": {"msgs_per_s": round(self.msgs_per_s, 1),
                      "trades_per_s": round(self.trades_per_s, 2)},
            "market_count": len(markets),
            "markets": markets,
            # Which publisher arm these numbers came from. Until 2026-09-04 both
            # arms were applied, so every total and rate here was ~2x the truth
            # and the book was walked backwards by the slow arm's late copies.
            "arms": arms or {},
        }


def _write_atomic(path: str, obj: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(orjson.dumps(obj))
    os.replace(tmp, path)


def run(link_ifname: str, group: str, ports: set[int], out_path: str,
        flush_ms: int, meta: dict, dz_channel: int | None = None) -> None:
    group_bytes = inet_aton(group)
    sock = _open_afpacket(link_ifname)
    decoder = DzDecoder()
    arbiter = ArmArbiter(dz_channel)
    state = LiveState()
    next_flush = time.monotonic() + flush_ms / 1000.0
    _log.info("live feed: %s group=%s ports=%s -> %s", link_ifname, group, sorted(ports), out_path)
    try:
        while True:
            readable, _w, _e = select.select([sock], [], [], 0.5)
            if readable:
                try:
                    data = sock.recv(_RECV_BUFSIZE)
                except OSError:
                    continue
                t = now_ns()
                payload = _udp_payload(data, group_bytes, ports)
                if payload is None:
                    continue
                channel = frame_channel(payload)
                if channel is None:
                    continue
                arbiter.note_frame(channel, t)
                events = decoder.decode(payload, t)
                # Offer both arms to the arbiter, apply only the winner's. The
                # loser's copy of a quote lands ~5 ms late, and applying it on
                # top of a fresher update rolled the book back to a stale top of
                # book in 9.5% of all quotes (15% of BTC's) when measured live.
                for e in events:
                    if e.kind == Kind.TRADE and e.size is not None:
                        arbiter.observe_trade(channel, (e.market, e.price, e.size), t)
                if not arbiter.accepts(channel, t):
                    continue
                state.frames += 1
                state._win_frames += 1
                state.apply(events)
            state.tick_rates()
            if time.monotonic() >= next_flush:
                _write_atomic(out_path, state.snapshot(meta, arbiter.stats(now_ns())))
                next_flush = time.monotonic() + flush_ms / 1000.0
    finally:
        sock.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--link", default="doublezero1", help="Interface name to tap via AF_PACKET")
    ap.add_argument("--group", default="233.84.178.3")
    ap.add_argument("--mktdata-port", type=int, default=31000)
    ap.add_argument("--refdata-port", type=int, default=41000)
    ap.add_argument("--out", default="data/dz_feed_state.json")
    ap.add_argument("--flush-ms", type=int, default=1000)
    ap.add_argument("--device", default="fr2-dzx-001")
    ap.add_argument("--metro", default="Frankfurt")
    ap.add_argument("--dz-channel", type=int, default=None,
                    help="Force a DZ frame Channel ID instead of arbitrating the "
                         "publisher arms automatically (see sources/dz_feed/arms.py)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    meta = {
        "source": "DoubleZero edge feed",
        "group_code": "edge-kalshi-perps-tob",
        "group": args.group,
        "ports": {"mktdata": args.mktdata_port, "refdata": args.refdata_port},
        "device": args.device,
        "metro": args.metro,
    }
    run(args.link, args.group, {args.mktdata_port, args.refdata_port}, args.out,
        args.flush_ms, meta, args.dz_channel)


if __name__ == "__main__":
    main()
