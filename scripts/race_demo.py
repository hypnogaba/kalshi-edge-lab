# scripts/race_demo.py
"""Terminal "race" demo: run the latency-race pipeline on REAL Kalshi trades.

HONESTY NOTE (read this): this script captures REAL Kalshi trades, but the
"DoubleZero" side is a SIMULATED time-shift of those same real trades (a fixed
-edge_ms shift applied to each event). It exists to show the race OUTPUT
FORMAT (matching, stats, histogram, report) working end-to-end on live data
before the actual DZ feed is available. It is NOT a latency measurement.
Real numbers require the DZ feed running on the server -- see scripts/run_race.py.

Run: uv run python -m scripts.race_demo --minutes 1 --near 6 --edge-ms 8
"""
import argparse
import dataclasses
import hashlib
import re
import sys
import time
from pathlib import Path

import httpx

from common.clock import now_ns
from common.event import Event, Kind, Side, Source
from race.match import match_trades
from race.report import render_report
from race.stats import latency_stats
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets

Frame = tuple[int, Event]

_THRESHOLD_RE = re.compile(r"-T\d+(?:\.\d+)?$")
_BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"
_SERIES = ("KXBTC", "KXBTCD")


def _banner(edge_ms: float) -> str:
    return (
        f"=== FORMAT DEMO — the DoubleZero side is SIMULATED (fixed -{edge_ms} ms shift of "
        "the same real trades). This shows the race OUTPUT FORMAT on live Kalshi data. It is "
        "NOT a latency measurement. Real numbers need the DZ feed on the server "
        "(scripts/run_race.py). ==="
    )


def _btc_spot() -> float:
    """One-shot Binance BTC/USDT spot, used only to pick near-the-money markets."""
    r = httpx.get(_BINANCE_URL, params={"symbol": "BTCUSDT"}, timeout=10.0)
    r.raise_for_status()
    return float(r.json()["price"])


def _stable_seq(trade_id: str) -> int:
    """Stable int seq derived from Kalshi's hex/uuid trade_id, so match_trades
    can match feed A and feed B on (market, seq) exactly."""
    return int(hashlib.blake2b(trade_id.encode(), digest_size=8).hexdigest(), 16)


def build_watchlist(client: KalshiRestClient, near: int) -> list[str]:
    """Merge KXBTC + KXBTCD open markets, keep only -T<number> threshold
    tickers, and return the `near` nearest to current BTC spot."""
    tickers: list[str] = []
    for series in _SERIES:
        try:
            tickers.extend(m["ticker"] for m in client.markets(series))
        except Exception as e:  # noqa: BLE001 - keep going with whatever series worked
            print(f"warning: could not fetch series {series}: {e}", file=sys.stderr)
    threshold_tickers = [t for t in tickers if _THRESHOLD_RE.search(t)]
    spot = _btc_spot()
    return nearest_markets(threshold_tickers, spot, near)


def _decode_trade(ticker: str, t: dict, t_arrival_ns: int) -> Event:
    price = round(float(t["yes_price_dollars"]) * 100)
    size = int(float(t["count_fp"]))
    side = Side.BUY if t.get("taker_side") == "yes" else Side.SELL
    seq = _stable_seq(t["trade_id"])
    return Event(source=Source.KALSHI_REST, t_arrival_ns=t_arrival_ns, market=ticker,
                 kind=Kind.TRADE, price=price, size=size, side=side, seq=seq)


def capture_real_trades(client: KalshiRestClient, tickers: list[str], duration_s: float,
                         poll_s: float = 1.0) -> list[Frame]:
    """Poll each market's recent trades until the deadline, dedup by trade_id,
    and stamp each NEW trade with the local arrival clock -- this is feed A."""
    frames: list[Frame] = []
    seen: set[str] = set()
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        for ticker in tickers:
            try:
                trades = client.trades(ticker, limit=50)
            except Exception as e:  # noqa: BLE001 - keep polling other markets
                print(f"warning: trades poll failed for {ticker}: {e}", file=sys.stderr)
                continue
            for tr in trades:
                tid = tr.get("trade_id")
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                ev = _decode_trade(ticker, tr, now_ns())
                frames.append((ev.t_arrival_ns, ev))
        time.sleep(poll_s)
    return frames


def simulate_dz_feed(feed_a: list[Frame], edge_ms: float) -> list[Frame]:
    """Feed B: the SAME real trades, shifted -edge_ms in arrival time. This is
    a fixed simulated time-shift, not a second live feed."""
    edge_ns = int(edge_ms * 1e6)
    return [
        (t - edge_ns, dataclasses.replace(ev, t_arrival_ns=t - edge_ns, source=Source.DZ_FEED))
        for t, ev in feed_a
    ]


def ascii_histogram(deltas_ms: list[float], bins: int = 10, width: int = 40) -> str:
    if not deltas_ms:
        return "(no data)"
    lo, hi = min(deltas_ms), max(deltas_ms)
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    span = hi - lo
    counts = [0] * bins
    for d in deltas_ms:
        idx = min(int((d - lo) / span * bins), bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    lines = []
    for i, c in enumerate(counts):
        b_lo = lo + i * span / bins
        b_hi = lo + (i + 1) * span / bins
        bar = "#" * max(1, round(c / max_count * width)) if c else ""
        lines.append(f"  [{b_lo:9.2f}, {b_hi:9.2f}) ms | {bar} {c}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=1,
                     help="Real-trade capture duration in minutes (default: 1)")
    ap.add_argument("--near", type=int, default=6,
                     help="Number of near-the-money threshold markets to watch (default: 6)")
    ap.add_argument("--edge-ms", type=float, default=8.0,
                     help="Simulated DoubleZero edge in ms; feed B is shifted -edge_ms (default: 8.0)")
    ap.add_argument("--window-ms", type=float, default=50.0,
                     help="Fallback match tolerance in ms (default: 50.0)")
    ap.add_argument("--out-dir", default="data/race_demo",
                     help="Output directory for the report PNG (default: data/race_demo)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    banner = _banner(args.edge_ms)
    print(banner)

    client = KalshiRestClient()
    try:
        print("Building near-money watchlist (KXBTC + KXBTCD, -T thresholds only)...")
        tickers = build_watchlist(client, args.near)
        if not tickers:
            print("No near-money threshold markets found; nothing to capture.")
            print(banner)
            return 0
        print(f"Watchlist ({len(tickers)}): {', '.join(tickers)}")

        duration_s = args.minutes * 60
        print(f"Capturing REAL Kalshi trades for {args.minutes} minute(s)...")
        feed_a = capture_real_trades(client, tickers, duration_s)
    finally:
        client.close()

    n_a = len(feed_a)
    print(f"\nreal trades captured: {n_a}")
    if n_a == 0:
        print("Market was too quiet -- zero real trades captured in this window.")
        print("Try a longer --minutes (e.g. --minutes 5) or a wider --near.")
        print(banner)
        return 0

    feed_b = simulate_dz_feed(feed_a, args.edge_ms)

    window_ns = int(args.window_ms * 1e6)
    pairs, discarded_a, discarded_b = match_trades(feed_a, feed_b, window_ns=window_ns)
    deltas = [p.delta_ns for p in pairs]
    stats = latency_stats(deltas)

    match_rate = (len(pairs) / n_a) if n_a else 0.0
    print(f"matched pairs: {len(pairs)}   match_rate: {match_rate:.1%}   "
          f"(discarded_real={discarded_a} discarded_simulated={discarded_b})")
    print(f"p10={stats.get('p10_ms')}ms  p50={stats.get('p50_ms')}ms  "
          f"p90={stats.get('p90_ms')}ms  p99={stats.get('p99_ms')}ms")
    print("note: negative = DoubleZero first (SIMULATED)")

    deltas_ms = [d / 1e6 for d in deltas]
    print("\nDelta histogram (ms, negative = simulated DZ first):")
    print(ascii_histogram(deltas_ms))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "race_demo.png"
    render_report(deltas, str(out_png),
                  title="Race format demo — SIMULATED edge on real Kalshi trades")
    print(f"\nreport: {out_png}")

    print()
    print(banner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
