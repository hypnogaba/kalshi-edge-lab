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
