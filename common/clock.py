"""Single monotonic arrival clock. CLOCK_MONOTONIC_RAW on Linux (the DZ server);
falls back to monotonic_ns on platforms without RAW (e.g. macOS dev)."""
import time


def now_ns() -> int:
    raw = getattr(time, "CLOCK_MONOTONIC_RAW", None)
    if raw is not None:
        try:
            return time.clock_gettime_ns(raw)
        except OSError:
            pass
    return time.monotonic_ns()
