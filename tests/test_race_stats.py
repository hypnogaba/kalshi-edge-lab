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
    assert stats["p95_ms"] == 9.55  # idx=8.55 -> between 9 and 10
    assert stats["p99_ms"] == 9.91  # idx=8.91 -> between 9 and 10
    assert stats["win_rate"] == 0.0  # all deltas positive -> DoubleZero never first


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
    assert stats["p95_ms"] == 3.0
    assert stats["win_rate"] == 0.0  # single positive delta -> DoubleZero never first


def test_negative_deltas_supported():
    stats = latency_stats([-2_000_000, 1_000_000])
    assert stats["n"] == 2
    assert stats["min_ms"] == -2.0
    assert stats["max_ms"] == 1.0
    assert stats["mean_ms"] == -0.5
    # idx=0.95*1=0.95 -> between -2 and 1: -2 + 0.95*3 = 0.85
    assert stats["p95_ms"] == 0.85
    assert stats["win_rate"] == 50.0  # 1 of 2 deltas negative (DoubleZero first)


def test_win_rate_and_p95_hand_computable():
    # Mix of negative (DoubleZero first) and positive (public first) deltas,
    # shuffled to prove sorting happens. Sorted ms: -8,-6,-4,-2,-1,1,2,3,5,9
    ms_values = [3, -6, 9, -1, 2, -8, 5, -4, 1, -2]
    deltas_ns = [v * 1_000_000 for v in ms_values]

    stats = latency_stats(deltas_ns)

    assert stats["n"] == 10
    # 5 of 10 deltas are negative (DoubleZero arrived first)
    assert stats["win_rate"] == 50.0
    # idx=0.95*9=8.55 -> between sorted[8]=5 and sorted[9]=9: 5 + 0.55*4 = 7.2
    assert stats["p95_ms"] == 7.2
    # idx=4.5 -> between sorted[4]=-1 and sorted[5]=1: -1 + 0.5*2 = 0.0
    assert stats["p50_ms"] == 0.0
