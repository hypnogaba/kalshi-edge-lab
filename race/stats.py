"""Latency-delta summary stats. Pure, no I/O.

Percentiles use linear interpolation between the two nearest ranks
(the same method as numpy's default "linear" percentile): for a sorted
list of n values, index = p/100 * (n-1); interpolate between the
floor and ceil neighbors by the fractional part.
"""


def latency_stats(deltas_ns: list[int]) -> dict:
    if not deltas_ns:
        return {"n": 0}

    ms = sorted(d / 1e6 for d in deltas_ns)
    n = len(ms)

    def pct(p: float) -> float:
        if n == 1:
            return round(ms[0], 3)
        idx = (p / 100) * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        value = ms[lo] + frac * (ms[hi] - ms[lo])
        return round(value, 3)

    return {
        "n": n,
        "mean_ms": round(sum(ms) / n, 3),
        "p10_ms": pct(10),
        "p50_ms": pct(50),
        "p90_ms": pct(90),
        "p99_ms": pct(99),
        "min_ms": round(ms[0], 3),
        "max_ms": round(ms[-1], 3),
    }
