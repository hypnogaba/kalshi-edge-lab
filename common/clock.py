"""Arrival clocks.

`now_ns` is the monotonic one: CLOCK_MONOTONIC_RAW on Linux (the DZ server),
falling back to monotonic_ns where RAW is absent (e.g. macOS dev). It has an
arbitrary epoch, so it is only ever valid for comparing two arrivals measured
on THIS host -- which is exactly what the feed-vs-feed race needs.

`wall_ns` is CLOCK_REALTIME: comparable to the venue's own exchange timestamp,
and therefore the only clock that can answer "how long did this take to get
here". It inherits every NTP wobble, so anything derived from it must be
published next to the measured clock offset (see `clock_offset_ms`).
"""
import time


def now_ns() -> int:
    raw = getattr(time, "CLOCK_MONOTONIC_RAW", None)
    if raw is not None:
        try:
            return time.clock_gettime_ns(raw)
        except OSError:
            pass
    return time.monotonic_ns()


def wall_ns() -> int:
    """Wall-clock nanoseconds since the Unix epoch (CLOCK_REALTIME)."""
    return time.time_ns()


def parse_chrony_tracking(csv: str) -> dict | None:
    """Turn one `chronyc -c tracking` line into a clock-quality summary.

    Returns None for anything unusable: a short line, unparseable numbers, or a
    daemon that is not actually synchronised yet.
    """
    # chronyc -c tracking emits 14 fields:
    #  0 ref_id        1 ref_host     2 stratum         3 ref_time
    #  4 system_time   5 last_offset  6 rms_offset      7 freq
    #  8 residual_freq 9 skew        10 root_delay     11 root_dispersion
    # 12 update_interval             13 leap
    # Counting `residual_freq` out of that list silently reads `skew` (a number
    # in the millions right after a restart) as the root delay, which turns a
    # sub-millisecond error bound into a plausible-looking 500-second one.
    f = csv.strip().split(",")
    if len(f) < 14:
        return None
    try:
        stratum = int(f[2])
        system_time = float(f[4])
        rms_offset = float(f[6])
        root_delay = float(f[10])
        root_dispersion = float(f[11])
        leap = f[13].strip()
    except (ValueError, IndexError):
        return None
    if stratum == 0 or leap == "Not synchronised":
        return None
    return {
        "source": "chrony",
        "stratum": stratum,
        "offset_ms": round(system_time * 1000, 4),
        "rms_offset_ms": round(rms_offset * 1000, 4),
        "error_ms": round((root_dispersion + root_delay / 2) * 1000, 3),
    }


def clock_offset_ms() -> dict | None:
    """How far this host's wall clock sits from true time, per the local NTP
    daemon. Returns None when chrony is not installed or not yet synchronised.

    Every absolute latency we publish is only as good as this number, so it is
    carried into the snapshot and shown on the page rather than being assumed.

    `offset_ms` is chrony's own estimate of the remaining error (signed, tiny
    once locked). `error_ms` is the honest bound to quote: root dispersion plus
    half the root delay, i.e. the worst case given the whole chain of servers
    upstream of us.
    """
    import shutil
    import subprocess

    if shutil.which("chronyc") is None:
        return None
    try:
        out = subprocess.run(["chronyc", "-c", "tracking"], capture_output=True,
                             text=True, timeout=2.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return parse_chrony_tracking(out.stdout)
