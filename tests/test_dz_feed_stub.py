import inspect

from sources.dz_feed import decoder as dz_decoder


def test_decode_signature_matches_kalshi():
    sig = inspect.signature(dz_decoder.decode)
    assert list(sig.parameters) == ["raw", "t_arrival_ns"]
