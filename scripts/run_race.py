# scripts/run_race.py
"""End-to-end Kalshi-vs-DoubleZero latency race, run from ONE host.

Captures the public Kalshi WS (the "direct from Kalshi" baseline) and the
DoubleZero Kalshi edge feed simultaneously, decodes TRADE events from both,
matches them, and reports the arrival-time delta (dz - public; negative
means DoubleZero arrived first / faster).

Run: uv run python -m scripts.run_race --market KXBTC-25DEC31 --minutes 2
Offline wiring check (no feeds/keys needed):
  uv run python -m scripts.run_race --selfcheck
"""
import argparse
import asyncio
import dataclasses
import logging
import sys
from pathlib import Path

from common.config import kalshi_prod
from common.event import Event, Kind, Side, Source
from common.storage import read_frames
from race.match import match_trades
from race.report import render_report
from race.stats import latency_stats
from sources.dz_feed.capture import (
    DEFAULT_GROUP,
    DEFAULT_MKTDATA_PORT,
    DEFAULT_REFDATA_PORT,
)
from sources.dz_feed.capture import capture as dz_capture
from sources.dz_feed.decoder import DzDecoder
from sources.kalshi_ws.capture import capture as kalshi_capture
from sources.kalshi_ws.decoder import decode as kalshi_decode

_log = logging.getLogger(__name__)

Frame = tuple[int, Event]

_SELFCHECK_N = 50
_SELFCHECK_DELAY_NS = 3_000_000
_SELFCHECK_SPACING_NS = 10_000_000
_SELFCHECK_MARKET = "KXSELFCHECK-TEST"


def _load_public_trades(path: Path) -> list[Frame]:
    """Decode the public Kalshi WS capture, keeping only TRADE events."""
    trades: list[Frame] = []
    if not path.exists():
        return trades
    for t, payload in read_frames(path):
        for ev in kalshi_decode(payload, t):
            if ev.kind == Kind.TRADE:
                trades.append((t, ev))
    return trades


def _load_dz_trades(path: Path) -> list[Frame]:
    """Decode the DZ edge feed capture with ONE decoder instance across all
    frames, so InstrumentDefinition (0x02) messages populate the registry
    before later Quote/Trade messages need it. Keep only TRADE events."""
    trades: list[Frame] = []
    if not path.exists():
        return trades
    decoder = DzDecoder()
    for t, payload in read_frames(path):
        for ev in decoder.decode(payload, t):
            if ev.kind == Kind.TRADE:
                trades.append((t, ev))
    return trades


async def _run_captures(cfg, markets: list[str], args: argparse.Namespace,
                         public_path: Path, dz_path: Path, duration_s: float) -> None:
    """Run the public Kalshi WS capture (async) and the DZ multicast capture
    (blocking, so it runs on a thread) concurrently for `duration_s` seconds."""
    await asyncio.gather(
        kalshi_capture(cfg, markets, str(public_path), duration_s),
        asyncio.to_thread(
            dz_capture, args.group, args.mktdata_port, args.refdata_port, args.iface,
            str(dz_path), duration_s,
        ),
    )


def _print_race_summary(pairs, discarded_a: int, discarded_b: int, n_a: int, n_b: int) -> None:
    match_rate = (len(pairs) / n_a) if n_a else 0.0
    stats = latency_stats([p.delta_ns for p in pairs])
    print(f"public trades: {n_a}   dz trades: {n_b}")
    print(f"matched pairs: {len(pairs)}   match_rate: {match_rate:.1%}   "
          f"(discarded_public={discarded_a} discarded_dz={discarded_b})")
    print(f"p10={stats.get('p10_ms')}ms  p50={stats.get('p50_ms')}ms  "
          f"p90={stats.get('p90_ms')}ms  p99={stats.get('p99_ms')}ms")
    print("delta = dz_arrival - public_arrival; negative = DoubleZero faster")


def _run_normal(args: argparse.Namespace) -> int:
    try:
        cfg = kalshi_prod()
    except RuntimeError:
        print(
            "Public Kalshi WS baseline needs a Kalshi PROD key in .env "
            "(KALSHI_PROD_KEY_ID + secrets/kalshi_prod_key.pem). The DZ feed side "
            "needs the doublezero1 tunnel + access pass + the Kalshi feed's "
            "multicast group/ports (from `doublezero multicast group list`).",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    public_path = out_dir / "public.bin"
    dz_path = out_dir / "dz.bin"

    markets = [m.strip() for m in args.market.split(",")]
    duration_s = args.minutes * 60

    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:  # noqa: BLE001, S110 - uvloop is an optional speedup
        pass

    asyncio.run(_run_captures(cfg, markets, args, public_path, dz_path, duration_s))

    public_trades = _load_public_trades(public_path)
    dz_trades = _load_dz_trades(dz_path)

    window_ns = args.window_ms * 1e6
    pairs, discarded_public, discarded_dz = match_trades(
        public_trades, dz_trades, window_ns=window_ns,
    )
    _print_race_summary(pairs, discarded_public, discarded_dz,
                         len(public_trades), len(dz_trades))

    out_png = out_dir / "race.png"
    render_report([p.delta_ns for p in pairs], str(out_png),
                  title="Kalshi via DoubleZero vs public")
    print(f"report: {out_png}")
    return 0


def _synthetic_trade(i: int, base_t_ns: int) -> Frame:
    t = base_t_ns + i * _SELFCHECK_SPACING_NS
    price = 1 + (i % 99)
    size = 1 + (i % 20)
    side = Side.YES if i % 2 == 0 else Side.NO
    ev = Event(source=Source.KALSHI_WS, t_arrival_ns=t, market=_SELFCHECK_MARKET,
               kind=Kind.TRADE, price=price, size=size, side=side, seq=i)
    return t, ev


def _run_selfcheck(args: argparse.Namespace) -> int:
    """Prove the match/stats/report wiring works end-to-end, offline: build a
    synthetic feed A of 50 TRADE events, and feed B = the same events with
    t_arrival_ns += 3ms (same seq), so every trade must match exactly and the
    reported p50 delta must be exactly +3.0 ms."""
    base_t_ns = 1_000_000_000
    feed_a = [_synthetic_trade(i, base_t_ns) for i in range(_SELFCHECK_N)]
    feed_b = [
        (t + _SELFCHECK_DELAY_NS,
         dataclasses.replace(ev, t_arrival_ns=t + _SELFCHECK_DELAY_NS, source=Source.DZ_FEED))
        for t, ev in feed_a
    ]

    window_ns = args.window_ms * 1e6
    pairs, discarded_a, discarded_b = match_trades(feed_a, feed_b, window_ns=window_ns)
    match_rate = (len(pairs) / len(feed_a)) if feed_a else 0.0
    stats = latency_stats([p.delta_ns for p in pairs])

    print(f"synthetic trades: {len(feed_a)}")
    print(f"matched pairs: {len(pairs)}   match_rate: {match_rate:.1%}   "
          f"(discarded_a={discarded_a} discarded_b={discarded_b})")
    print(f"stats: {stats}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "selfcheck_race.png"
    render_report([p.delta_ns for p in pairs], str(out_png),
                  title="Offline selfcheck: synthetic +3ms delay")
    print(f"report: {out_png}")

    expected_ms = _SELFCHECK_DELAY_NS / 1e6
    ok = match_rate == 1.0 and stats.get("p50_ms") == expected_ms
    print("SELFCHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=2,
                     help="Capture duration in minutes (default: 2)")
    ap.add_argument("--market", default=None,
                     help="Kalshi ticker(s), comma-separated, for the public WS baseline")
    ap.add_argument("--out-dir", default="data/race", help="Output directory (default: data/race)")
    ap.add_argument("--group", default=DEFAULT_GROUP, help="DZ multicast group address")
    ap.add_argument("--mktdata-port", type=int, default=DEFAULT_MKTDATA_PORT)
    ap.add_argument("--refdata-port", type=int, default=DEFAULT_REFDATA_PORT)
    ap.add_argument("--iface", default=None,
                     help="Local interface IP to join DZ multicast on (e.g. doublezero1's address)")
    ap.add_argument("--window-ms", type=float, default=50,
                     help="Fallback match tolerance in ms (default: 50)")
    ap.add_argument("--selfcheck", action="store_true",
                     help="Validate the match/stats/report wiring offline; needs no feeds/keys")
    args = ap.parse_args(argv)
    if not args.selfcheck and not args.market:
        ap.error("--market is required (unless --selfcheck)")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    if args.selfcheck:
        return _run_selfcheck(args)
    return _run_normal(args)


if __name__ == "__main__":
    sys.exit(main())
