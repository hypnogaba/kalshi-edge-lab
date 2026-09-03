"""The absolute-latency reporting in scripts.dz_latency_race."""
from scripts.dz_latency_race import _HIST_HI_MS, _HIST_LO_MS, _histogram


def test_histogram_counts_every_sample_including_the_tail():
    """A value past the top of the axis must be counted, never dropped.

    The range is chosen for readability, so if out-of-range samples were
    silently discarded the chart would flatter whichever feed has the heavier
    tail -- exactly the thing the chart exists to expose.
    """
    dz = [50.0, 51.0, 51.0, 52.0, 184.0, 44.0]
    public = [57.0, 58.0, 58.0, 238.0]

    h = _histogram(dz, public)

    assert sum(h["dz"]) + h["dz_under"] + h["dz_over"] == len(dz)
    assert sum(h["public"]) + h["public_under"] + h["public_over"] == len(public)
    assert h["dz_over"] == 1      # 184.0
    assert h["dz_under"] == 1     # 44.0
    assert h["public_over"] == 1  # 238.0
    assert h["public_under"] == 0


def test_histogram_puts_a_value_in_the_bin_that_contains_it():
    h = _histogram([50.4, 51.6], [])
    width = h["width_ms"]
    filled = [i for i, c in enumerate(h["dz"]) if c]

    assert [round(_HIST_LO_MS + i * width, 1) for i in filled] == [50.0, 51.0]


def test_histogram_boundaries_are_half_open():
    """lo belongs to the first bin, hi counts as overflow -- no double count."""
    h = _histogram([_HIST_LO_MS, _HIST_HI_MS], [])

    assert h["dz"][0] == 1
    assert h["dz_over"] == 1
    assert h["dz_under"] == 0


def test_histogram_ignores_missing_values():
    """dz_transport and exch_to_pub are None when a frame carried no send
    timestamp; a None must not be counted as a sample."""
    h = _histogram([50.0, None, 51.0], [None])

    assert sum(h["dz"]) == 2
    assert sum(h["public"]) + h["public_under"] + h["public_over"] == 0


def test_empty_input_produces_an_empty_but_well_formed_histogram():
    h = _histogram([], [])

    assert sum(h["dz"]) == 0
    assert len(h["dz"]) == len(h["public"])
    assert h["lo_ms"] < h["hi_ms"]


# --- the arithmetic behind the published number -----------------------------

from scripts.dz_latency_race import Half, RaceState

MS = 1_000_000


def _pair(state, key, *, exch_ms, dz_arrival_ms, pub_arrival_ms, pub_send_ms=None):
    """Feed the same trade in on both sides, in milliseconds for legibility."""
    exch = exch_ms * MS
    state.add_dz(key, Half(mono_ns=dz_arrival_ms * MS, wall_ns=dz_arrival_ms * MS,
                           exch_ts_ns=exch,
                           pub_ts_ns=None if pub_send_ms is None else pub_send_ms * MS))
    state.add_pub(key, Half(mono_ns=pub_arrival_ms * MS, wall_ns=pub_arrival_ms * MS,
                            exch_ts_ns=exch))


def test_totals_are_arrival_minus_the_venue_stamp_on_each_side():
    st = RaceState(1440.0)
    _pair(st, ("KXBTCPERP", 1, 2, 3), exch_ms=1_000_000,
          dz_arrival_ms=1_000_051, pub_arrival_ms=1_000_057, pub_send_ms=1_000_002)

    a = st.snapshot(1440.0)["absolute"]

    assert a["n"] == 1
    assert a["dz_total"]["p50_ms"] == 51.0
    assert a["public_total"]["p50_ms"] == 57.0


def test_the_two_legs_sum_to_the_total():
    """The split is only meaningful if it reconstructs the number above it."""
    st = RaceState(1440.0)
    _pair(st, ("KXETHPERP", 1, 2, 3), exch_ms=2_000_000,
          dz_arrival_ms=2_000_051, pub_arrival_ms=2_000_057, pub_send_ms=2_000_002)

    a = st.snapshot(1440.0)["absolute"]

    assert a["exch_to_pub"]["p50_ms"] == 2.0
    assert a["dz_transport"]["p50_ms"] == 49.0
    assert a["exch_to_pub"]["p50_ms"] + a["dz_transport"]["p50_ms"] == a["dz_total"]["p50_ms"]


def test_a_frame_without_a_send_stamp_still_yields_a_total():
    """The total needs only the venue's clock and ours, so it must survive a
    frame that carried no publisher timestamp -- only the split should vanish."""
    st = RaceState(1440.0)
    _pair(st, ("KXSOLPERP", 1, 2, 3), exch_ms=3_000_000,
          dz_arrival_ms=3_000_051, pub_arrival_ms=3_000_057, pub_send_ms=None)

    a = st.snapshot(1440.0)["absolute"]

    assert a["dz_total"]["p50_ms"] == 51.0
    assert a["dz_transport"] is None
    assert a["exch_to_pub"] is None


def test_a_stepped_clock_is_rejected_rather_than_stored_for_a_day():
    """A wall-clock step would otherwise own max and p99 for the whole window."""
    st = RaceState(1440.0)
    _pair(st, ("KXBTCPERP", 1, 2, 3), exch_ms=4_000_000,
          dz_arrival_ms=4_000_051, pub_arrival_ms=4_000_057)
    # clock jumped back an hour: arrival now "precedes" the venue stamp
    _pair(st, ("KXBTCPERP", 9, 9, 9), exch_ms=4_000_100,
          dz_arrival_ms=4_000_100 - 3_600_000, pub_arrival_ms=4_000_157)

    snap = st.snapshot(1440.0)

    assert snap["absolute"]["n"] == 1
    assert snap["implausible_dropped"] == 1
    assert snap["absolute"]["dz_total"]["max_ms"] == 51.0
    # the pair still counts as matched: only the absolute sample was refused
    assert snap["matched_total"] == 2


def test_absolute_uses_matched_pairs_only_so_both_columns_share_a_sample():
    """An unmatched half must not reach the absolute series, or DoubleZero and
    the public feed would be summarising different sets of trades."""
    st = RaceState(1440.0)
    st.add_dz(("KXBTCPERP", 1, 2, 3),
              Half(mono_ns=51 * MS, wall_ns=51 * MS, exch_ts_ns=0 * MS))

    snap = st.snapshot(1440.0)

    assert snap["dz_seen"] == 1
    assert snap["matched_total"] == 0
    assert snap["absolute"]["n"] == 0


# --- the two percentile paths must not disagree -----------------------------

import random

import scripts.dz_latency_race as race


def test_numpy_and_pure_python_summaries_agree():
    """numpy is an optimisation, never a different answer.

    If the two paths drifted, the published percentiles would silently depend
    on whether numpy happened to be installed on the host.
    """
    if race._np is None:  # pragma: no cover - numpy present in this env
        return
    rng = random.Random(20260903)
    for size in (1, 2, 7, 100, 5000):
        values = [rng.gauss(51, 6) for _ in range(size)]
        with_numpy = race._summarise(list(values))

        saved, race._np = race._np, None
        try:
            pure = race._summarise(list(values))
        finally:
            race._np = saved

        assert with_numpy == pure, f"paths disagree at n={size}"


def test_summarise_skips_missing_and_reports_the_count_it_used():
    out = race._summarise([50.0, None, 52.0, None, 51.0])

    assert out["n"] == 3
    assert out["min_ms"] == 50.0
    assert out["max_ms"] == 52.0
    assert out["avg_ms"] == 51.0


def test_summarise_of_nothing_is_none_not_a_zero():
    """A missing measurement must read as absent, never as 0 ms -- a zero would
    be the fastest number on the page."""
    assert race._summarise([]) is None
    assert race._summarise([None, None]) is None
