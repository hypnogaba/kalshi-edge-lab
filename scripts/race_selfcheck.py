"""Validate the race harness end-to-end with no DZ feed needed.

Races the public Hyperliquid WS against a DELAYED REPLAY of itself: reads a
capture of real BTC trades, decodes it as feed A, then builds a synthetic
feed B by copying each trade event with the same seq (trade id) but
t_arrival_ns += 3_000_000 (a synthetic +3ms delay). Since both feeds carry
identical trades with identical ids, match_trades() should find (near-)all
of them by exact id, and latency_stats() should report p50 ~= +3.0 ms --
proving the matcher and stats measure the injected delay correctly. Real
DZ-vs-public numbers come once the DZ feed runs on the DZ-connected server.

Run: uv run python -m scripts.race_selfcheck data/race_a.bin
"""
import dataclasses
import sys

from common.event import Kind
from common.storage import read_frames
from race.match import match_trades
from race.report import render_report
from race.stats import latency_stats
from sources.hl_ws.decoder import decode

_SYNTHETIC_DELAY_NS = 3_000_000
_OUT_PNG = "data/race_selfcheck.png"


def main(path: str) -> int:
    feed_a: list[tuple[int, object]] = []
    for t, payload in read_frames(path):
        for ev in decode(payload, t):
            if ev.kind == Kind.TRADE:
                feed_a.append((t, ev))

    feed_b = [
        (t + _SYNTHETIC_DELAY_NS, dataclasses.replace(ev, t_arrival_ns=t + _SYNTHETIC_DELAY_NS))
        for t, ev in feed_a
    ]

    pairs, discarded_a, discarded_b = match_trades(feed_a, feed_b, window_ns=50_000_000)

    total_a = len(feed_a)
    match_rate = (len(pairs) / total_a) if total_a else 0.0
    stats = latency_stats([p.delta_ns for p in pairs])

    print(f"feed_a trades: {total_a}")
    print(f"matched pairs: {len(pairs)}")
    print(f"discarded_a: {discarded_a}  discarded_b: {discarded_b}")
    print(f"match_rate: {match_rate:.3%}")
    print(f"stats: {stats}")

    render_report(
        [p.delta_ns for p in pairs], _OUT_PNG,
        title="Latency race self-check (public HL WS vs +3ms delayed replay)",
    )
    print(f"PNG written: {_OUT_PNG}")

    expected_ms = _SYNTHETIC_DELAY_NS / 1e6
    ok = total_a > 0 and match_rate > 0.9 and abs(stats.get("p50_ms", 0.0) - expected_ms) < 0.5
    print("SELFCHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/race_a.bin"))
