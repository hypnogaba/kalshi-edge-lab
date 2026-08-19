"""Match TRADE events across two arrival streams on ONE host's clock.

Both inputs are lists of (t_arrival_ns, Event) tuples, already decoded from
whichever source. We never compare timestamps across machines -- both streams
must be stamped by the same local clock (see common.clock.now_ns).

Matching rule:
1. Primary: same market and same seq (trade id) -- exact, each element used once.
2. Fallback (for elements that didn't get an exact-id match, e.g. missing seq):
   same market, equal price and size (float tolerance), nearest-in-time within
   window_ns; each element used once.
"""
from dataclasses import dataclass

from common.event import Event, Kind

_PRICE_SIZE_TOL = 1e-9

Frame = tuple[int, Event]


@dataclass(frozen=True, slots=True)
class MatchedPair:
    market: str
    price: int | float | None
    size: int | float | None
    seq: int | None
    t_a_ns: int
    t_b_ns: int
    delta_ns: int


def _trade_frames(frames: list[Frame]) -> list[tuple[int, Frame]]:
    """Indices + frames, filtered to TRADE events only."""
    return [(i, f) for i, f in enumerate(frames) if f[1].kind == Kind.TRADE]


def match_trades(
    a: list[Frame], b: list[Frame], *, window_ns: int,
) -> tuple[list[MatchedPair], int, int]:
    trades_a = _trade_frames(a)  # [(orig_index_in_a, (t_ns, Event)), ...]
    trades_b = _trade_frames(b)
    b_by_idx: dict[int, Frame] = dict(trades_b)  # orig_index_in_b -> frame

    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[MatchedPair] = []

    # Pass 1: exact (market, seq) match.
    by_key: dict[tuple[str, int], list[int]] = {}
    for j, (_, ev) in trades_b:
        if ev.seq is not None:
            by_key.setdefault((ev.market, ev.seq), []).append(j)

    for i, (t_a, ev_a) in trades_a:
        if ev_a.seq is None:
            continue
        candidates = by_key.get((ev_a.market, ev_a.seq))
        if not candidates:
            continue
        # Pick nearest-in-time among candidates sharing the same id (should be unique).
        best_j = None
        best_dt = None
        for j in candidates:
            if j in used_b:
                continue
            t_b, _ = b_by_idx[j]
            dt = abs(t_b - t_a)
            if best_dt is None or dt < best_dt:
                best_dt = dt
                best_j = j
        if best_j is None:
            continue
        t_b, ev_b = b_by_idx[best_j]
        pairs.append(MatchedPair(
            market=ev_a.market, price=ev_a.price, size=ev_a.size, seq=ev_a.seq,
            t_a_ns=t_a, t_b_ns=t_b, delta_ns=t_b - t_a,
        ))
        used_a.add(i)
        used_b.add(best_j)

    # Pass 2: fallback price/size nearest-in-time match, within window_ns.
    for i, (t_a, ev_a) in trades_a:
        if i in used_a:
            continue
        best_j = None
        best_t_b = None
        best_dt = None
        for j, (t_b, ev_b) in trades_b:
            if j in used_b:
                continue
            if ev_b.market != ev_a.market:
                continue
            if ev_a.price is None or ev_b.price is None:
                continue
            if ev_a.size is None or ev_b.size is None:
                continue
            if abs(ev_a.price - ev_b.price) >= _PRICE_SIZE_TOL:
                continue
            if abs(ev_a.size - ev_b.size) >= _PRICE_SIZE_TOL:
                continue
            dt = abs(t_b - t_a)
            if dt > window_ns:
                continue
            if best_dt is None or dt < best_dt:
                best_dt = dt
                best_j = j
                best_t_b = t_b
        if best_j is None:
            continue
        pairs.append(MatchedPair(
            market=ev_a.market, price=ev_a.price, size=ev_a.size, seq=ev_a.seq,
            t_a_ns=t_a, t_b_ns=best_t_b, delta_ns=best_t_b - t_a,
        ))
        used_a.add(i)
        used_b.add(best_j)

    discarded_a = len(trades_a) - len(used_a)
    discarded_b = len(trades_b) - len(used_b)
    return pairs, discarded_a, discarded_b
