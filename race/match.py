"""Match TRADE events across two arrival streams on ONE host's clock.

Both inputs are lists of (t_arrival_ns, Event) tuples, already decoded from
whichever source. We never compare timestamps across machines -- both streams
must be stamped by the same local clock (see common.clock.now_ns).

Matching rule, the same one scripts/dz_latency_race.py uses live: the venue's
own view of the trade, which both feeds carry identically.

    (market, exchange timestamp in ms, price in ticks, contract count)

nearest-in-time within `window_ns`, each element on each side used at most once.

What this used to do, and why it could not work. Pass 1 matched on
`(market, seq)` with no time window at all. But the two feeds do not share an id
space, which docs/methodology.md says outright: on the public side `seq` is a
per-subscription MESSAGE counter that runs 1, 2, 3 across consecutive trades on
any market, and on the DoubleZero side it is the venue's u64 trade id. Matching
those pairs unrelated trades, unbounded in time. The test suite passed because
it built both sides with the same `seq`, which encodes the very assumption the
methodology says is false. tests/test_race_match.py now builds a UUID against a
u64, so that mistake fails instead of passing.

Both sides must arrive here already on ONE axis -- price in dollars per unit of
the underlying, size in contracts -- and carrying `exch_ts_ns`. Putting them
there needs the market's contract size, which only the DoubleZero reference data
publishes; scripts/run_race.py does it at load time.

`tick_of` gives the market's own price increment, which is what the price is
counted in. Rounding to whole dollars instead collapses the price to 0 on DOGE,
KSHIB, WLD and ADA and to 1 on XRP and SUI, so those markets would key on time
and size alone. It is a required argument on purpose: a default would be a
constant standing in for a per-market property, which is exactly the bug.
"""
from collections.abc import Callable
from dataclasses import dataclass

from common.event import Event, Kind

Frame = tuple[int, Event]
TickLookup = Callable[[str], float | None]


@dataclass(frozen=True, slots=True)
class MatchedPair:
    market: str
    price: int | float | None
    size: int | float | None
    exch_ts_ns: int
    t_a_ns: int
    t_b_ns: int
    delta_ns: int


def _trade_frames(frames: list[Frame]) -> list[tuple[int, Frame]]:
    """Indices + frames, filtered to TRADE events that can be keyed at all."""
    return [(i, f) for i, f in enumerate(frames)
            if f[1].kind == Kind.TRADE and f[1].exch_ts_ns
            and f[1].price is not None and f[1].size is not None]


def _key(ev: Event, tick_of: TickLookup) -> tuple | None:
    tick = tick_of(ev.market)
    if not tick or tick <= 0:
        return None   # no reference data: cannot be put on a common axis
    return (ev.market, ev.exch_ts_ns // 1_000_000,
            round(ev.price / tick), round(ev.size))


def match_trades(
    a: list[Frame], b: list[Frame], *, window_ns: float, tick_of: TickLookup,
) -> tuple[list[MatchedPair], int, int]:
    trades_a = _trade_frames(a)
    trades_b = _trade_frames(b)

    by_key: dict[tuple, list[int]] = {}
    b_by_idx: dict[int, Frame] = {}
    for j, frame in trades_b:
        b_by_idx[j] = frame
        k = _key(frame[1], tick_of)
        if k is not None:
            by_key.setdefault(k, []).append(j)

    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[MatchedPair] = []

    for i, (t_a, ev_a) in trades_a:
        k = _key(ev_a, tick_of)
        if k is None:
            continue
        best_j = best_t_b = best_dt = None
        for j in by_key.get(k, ()):
            if j in used_b:
                continue
            t_b, _ev_b = b_by_idx[j]
            dt = abs(t_b - t_a)
            if dt > window_ns:
                continue
            if best_dt is None or dt < best_dt:
                best_dt, best_j, best_t_b = dt, j, t_b
        if best_j is None:
            continue
        pairs.append(MatchedPair(
            market=ev_a.market, price=ev_a.price, size=ev_a.size,
            exch_ts_ns=ev_a.exch_ts_ns, t_a_ns=t_a, t_b_ns=best_t_b,
            delta_ns=best_t_b - t_a,
        ))
        used_a.add(i)
        used_b.add(best_j)

    return pairs, len(trades_a) - len(used_a), len(trades_b) - len(used_b)
