import time

from common.clock import now_ns, parse_chrony_tracking, wall_ns

# A real line from `chronyc -c tracking` on the DZ host, captured 2026-09-03.
# 14 fields: ref_id, ref_host, stratum, ref_time, system_time, last_offset,
# rms_offset, freq, residual_freq, skew, root_delay, root_dispersion,
# update_interval, leap.
_REAL_LINE = ("B97DBE38,185.125.190.56,3,1788459803.008376841,-0.000000113,"
              "-0.000713998,0.000713998,19.860,-481.306,1000000.000,"
              "0.020195609,19.055683136,0.2,Normal")


def test_now_ns_is_int_and_nondecreasing():
    a = now_ns()
    b = now_ns()
    assert isinstance(a, int)
    assert b >= a
    assert a > 0


def test_wall_ns_tracks_the_unix_epoch():
    """wall_ns must be comparable to a venue's exchange timestamp.

    now_ns counts from an arbitrary origin (uptime on Linux), so subtracting it
    from an exchange stamp yields nonsense. wall_ns is the one that may be.
    """
    assert abs(wall_ns() / 1e9 - time.time()) < 1.0


def test_chrony_tracking_error_bound_uses_root_delay_not_skew():
    """Field order regression: skew sat next to root_delay and got read as it.

    In this real sample skew is 1000000.000 and root_delay is 0.0202 s. Reading
    the wrong column turned a ~19.07 s error bound into ~500000 s while still
    looking like a plausible number, which would have silently invalidated
    every published latency figure.
    """
    out = parse_chrony_tracking(_REAL_LINE)

    assert out is not None
    assert out["stratum"] == 3
    # root_dispersion 19.055683136 + root_delay 0.020195609 / 2
    assert out["error_ms"] == 19065.781
    assert out["offset_ms"] == -0.0001
    assert out["rms_offset_ms"] == 0.714


def test_chrony_tracking_rejects_unsynchronised_and_malformed():
    unsynced = _REAL_LINE.rsplit(",", 1)[0] + ",Not synchronised"
    assert parse_chrony_tracking(unsynced) is None

    stratum_zero = _REAL_LINE.split(",")
    stratum_zero[2] = "0"
    assert parse_chrony_tracking(",".join(stratum_zero)) is None

    # A 13-field line (one column short) must be refused, not silently
    # misparsed by shifting every later field left.
    assert parse_chrony_tracking(",".join(_REAL_LINE.split(",")[:13])) is None
    assert parse_chrony_tracking("") is None
    assert parse_chrony_tracking("not,a,tracking,line") is None
