from race.stats import latency_stats


def test_empty_input_yields_n_zero_only():
    assert latency_stats([]) == {"n": 0}


def test_known_list_hand_computable_percentiles():
    # ms values 1..10 (deltas in ns), shuffled to prove sorting happens.
    ms_values = [7, 2, 10, 4, 1, 9, 3, 6, 8, 5]
    deltas_ns = [v * 1_000_000 for v in ms_values]

    stats = latency_stats(deltas_ns)

    # Linear interpolation percentiles (numpy "linear" method):
    # index = p/100 * (n-1), interpolate between sorted neighbors.
    assert stats["n"] == 10
    assert stats["mean_ms"] == 5.5
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 10.0
    assert stats["p10_ms"] == 1.9   # idx=0.9 -> between 1 and 2
    assert stats["p50_ms"] == 5.5   # idx=4.5 -> between 5 and 6
    assert stats["p90_ms"] == 9.1   # idx=8.1 -> between 9 and 10
    assert stats["p99_ms"] == 9.91  # idx=8.91 -> between 9 and 10


def test_single_value_all_percentiles_equal_the_value():
    stats = latency_stats([3_000_000])
    assert stats["n"] == 1
    assert stats["mean_ms"] == 3.0
    assert stats["min_ms"] == 3.0
    assert stats["max_ms"] == 3.0
    assert stats["p10_ms"] == 3.0
    assert stats["p50_ms"] == 3.0
    assert stats["p90_ms"] == 3.0
    assert stats["p99_ms"] == 3.0


def test_negative_deltas_supported():
    stats = latency_stats([-2_000_000, 1_000_000])
    assert stats["n"] == 2
    assert stats["min_ms"] == -2.0
    assert stats["max_ms"] == 1.0
    assert stats["mean_ms"] == -0.5
