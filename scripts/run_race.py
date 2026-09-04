# scripts/run_race.py
"""End-to-end Kalshi-vs-DoubleZero latency race, run from ONE host.

Capture-then-replay twin of scripts/dz_latency_race.py: it records both feeds
to disk, then decodes, matches and reports offline, so a run can be re-examined
after the fact. It measures the same thing, the same way, and the two are kept
deliberately in step -- same socket, same publisher-arm arbitration, same join
key. They drifted apart once already, and a reproduction path that quietly
disagrees with the live one is worse than none.

Both sides are put on ONE axis at load time, using the contract size from the
DoubleZero reference data: price in dollars per unit of the underlying, size in
contracts. Delta = dz_arrival - public_arrival; negative means DoubleZero
arrived first.

Run: uv run python -m scripts.run_race --market KXBTCPERP --minutes 2
Offline wiring check (no feeds/keys needed):
  uv run python -m scripts.run_race --selfcheck
"""
import argparse
import asyncio
import dataclasses
import logging
import sys
import time
from pathlib import Path

import orjson

from common.config import kalshi_prod
from common.event import Event, Kind, Side, Source
from common.storage import read_frames
from race.match import match_trades
from race.report import render_report
from race.stats import latency_stats
from sources.dz_feed.arms import ArmArbiter
from sources.dz_feed.capture import (
    DEFAULT_GROUP,
    DEFAULT_MKTDATA_PORT,
    DEFAULT_REFDATA_PORT,
)
from sources.dz_feed.capture import capture as dz_capture
from sources.dz_feed.contract_sizes import ContractSizes
from sources.dz_feed.decoder import DzDecoder, frame_channel
from sources.kalshi_ws.capture import capture as kalshi_capture
from sources.kalshi_ws.decoder import decode as kalshi_decode

_log = logging.getLogger(__name__)

Frame = tuple[int, Event]

_SELFCHECK_N = 50
_SELFCHECK_DELAY_NS = 3_000_000
_SELFCHECK_SPACING_NS = 10_000_000
_SELFCHECK_MARKET = "KXSELFCHECK-TEST"
_SELFCHECK_TICK = 0.5


def _load_dz_trades(path: Path, sizes: ContractSizes) -> tuple[list[Frame], DzDecoder]:
    """Decode the DZ edge feed capture with ONE decoder instance across all
    frames, so InstrumentDefinition (0x02) messages populate the registry before
    later Quote/Trade messages need it.

    The group carries two publisher arms, so the same arbiter the live reader
    uses runs over the replay too. Without it every trade appears twice and the
    duplicate sits in the matcher competing for its own twin. Sizes come out on
    the contract axis, so the public side can be compared to them.
    """
    trades: list[Frame] = []
    decoder = DzDecoder()
    if not path.exists():
        return trades, decoder
    arbiter = ArmArbiter()
    for t, payload in read_frames(path):
        channel = frame_channel(payload)
        if channel is None:
            continue
        arbiter.note_frame(channel, t)
        events = decoder.decode(payload, t)
        for ev in events:
            if ev.kind == Kind.TRADE and ev.size is not None:
                arbiter.observe_trade(channel, (ev.market, ev.price, ev.size), t)
        if not arbiter.accepts(channel, t):
            continue
        for ev in events:
            if ev.kind != Kind.TRADE or ev.size is None or not ev.exch_ts_ns:
                continue
            contract_size = sizes.learn_from(decoder.registry, ev.market)
            if contract_size is None:
                continue  # reference data for this market is not in the capture
            trades.append((t, dataclasses.replace(ev, size=ev.size / contract_size)))
    _log.info("dz arms: %s", arbiter.stats())
    return trades, decoder


def _load_public_trades(path: Path, sizes: ContractSizes) -> list[Frame]:
    """Decode the public perps WS capture, keeping TRADE events and putting
    their price on the DZ feed's axis (dollars per unit of the underlying).
    Counts are already contracts on this side."""
    trades: list[Frame] = []
    if not path.exists():
        return trades
    for t, payload in read_frames(path):
        for ev in kalshi_decode(payload, t):
            contract_size = sizes.get(ev.market)
            if contract_size is None:
                continue  # the DZ capture never named this market
            trades.append((t, dataclasses.replace(ev, price=ev.price / contract_size)))
    return trades


async def _run_captures(cfg, markets: list[str], args: argparse.Namespace,
                         public_path: Path, dz_path: Path, duration_s: float) -> None:
    """Run the public Kalshi WS capture (async) and the DZ multicast capture
    (blocking, so it runs on a thread) concurrently for `duration_s` seconds."""
    await asyncio.gather(
        kalshi_capture(cfg, markets, str(public_path), duration_s),
        asyncio.to_thread(
            dz_capture, args.group, args.mktdata_port, args.refdata_port, args.iface,
            str(dz_path), duration_s, args.link,
        ),
    )


def _print_race_summary(pairs, discarded_a: int, discarded_b: int, n_a: int, n_b: int) -> dict:
    match_rate = (len(pairs) / n_a) if n_a else 0.0
    stats = latency_stats([p.delta_ns for p in pairs])
    print(f"public trades: {n_a}   dz trades: {n_b}")
    print(f"matched pairs: {len(pairs)}   match_rate: {match_rate:.1%}   "
          f"(discarded_public={discarded_a} discarded_dz={discarded_b})")
    print(f"p10={stats.get('p10_ms')}ms  p50={stats.get('p50_ms')}ms  "
          f"p90={stats.get('p90_ms')}ms  p99={stats.get('p99_ms')}ms")
    print("delta = dz_arrival - public_arrival; negative = DoubleZero faster")
    return stats


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

    # DZ first: its reference data is what puts the public side on one axis.
    sizes = ContractSizes()
    dz_trades, _decoder = _load_dz_trades(dz_path, sizes)
    public_trades = _load_public_trades(public_path, sizes)

    window_ns = args.window_ms * 1e6
    pairs, discarded_public, discarded_dz = match_trades(
        public_trades, dz_trades, window_ns=window_ns, tick_of=sizes.tick,
    )
    stats = _print_race_summary(pairs, discarded_public, discarded_dz,
                                 len(public_trades), len(dz_trades))

    out_png = out_dir / "race.png"
    render_report([p.delta_ns for p in pairs], str(out_png),
                  title="Kalshi via DoubleZero vs public")
    print(f"report: {out_png}")

    match_rate = (len(pairs) / len(public_trades)) if public_trades else 0.0
    race_stats = {
        "stats": stats,
        "matched": len(pairs),
        "discarded_a": discarded_public,
        "discarded_b": discarded_dz,
        "match_rate": match_rate,
        "params": {
            "market": args.market,
            "group": args.group,
            "minutes": args.minutes,
            "window_ms": args.window_ms,
        },
        "captured_at": time.time(),
    }
    out_json = out_dir / "race_stats.json"
    out_json.write_bytes(orjson.dumps(race_stats))
    print(f"stats: {out_json}")
    return 0


def _synthetic_trade(i: int, base_t_ns: int) -> Frame:
    t = base_t_ns + i * _SELFCHECK_SPACING_NS
    # Prices sit on the tick, as a real trade does, and the exchange stamp is
    # the venue's -- identical on both feeds, which is the whole basis of the
    # join. Only the arrival time differs between the two synthetic feeds.
    price = _SELFCHECK_TICK * (2 + (i % 99))
    size = 1 + (i % 20)
    side = Side.BUY if i % 2 == 0 else Side.SELL
    ev = Event(source=Source.MARGIN_WS, t_arrival_ns=t, market=_SELFCHECK_MARKET,
               kind=Kind.TRADE, price=price, size=size, side=side,
               exch_ts_ns=t)
    return t, ev


def _run_selfcheck(args: argparse.Namespace) -> int:
    """Prove the match/stats/report wiring works end-to-end, offline: build a
    synthetic feed A of 50 TRADE events, and feed B = the same trades (same
    venue stamp, price and size) arriving 3 ms later, so every trade must match
    exactly and the reported p50 delta must be exactly +3.0 ms."""
    base_t_ns = 1_000_000_000
    feed_a = [_synthetic_trade(i, base_t_ns) for i in range(_SELFCHECK_N)]
    feed_b = [
        (t + _SELFCHECK_DELAY_NS,
         dataclasses.replace(ev, t_arrival_ns=t + _SELFCHECK_DELAY_NS, source=Source.DZ_FEED))
        for t, ev in feed_a
    ]

    window_ns = args.window_ms * 1e6
    pairs, discarded_a, discarded_b = match_trades(
        feed_a, feed_b, window_ns=window_ns, tick_of=lambda _m: _SELFCHECK_TICK)
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
                     help="Kalshi perp ticker(s), comma-separated, e.g. KXBTCPERP")
    ap.add_argument("--out-dir", default="data/race", help="Output directory (default: data/race)")
    ap.add_argument("--group", default=DEFAULT_GROUP, help="DZ multicast group address")
    ap.add_argument("--mktdata-port", type=int, default=DEFAULT_MKTDATA_PORT)
    ap.add_argument("--refdata-port", type=int, default=DEFAULT_REFDATA_PORT)
    ap.add_argument("--iface", default=None,
                     help="Local interface IP to join DZ multicast on (e.g. doublezero1's address)")
    ap.add_argument("--link", default=None,
                     help="Interface NAME (e.g. doublezero1) to capture the DZ feed via AF_PACKET; "
                          "required on the DZ tunnel, where a UDP multicast socket receives nothing")
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
