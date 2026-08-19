import inspect

import pytest

from sources.dz_feed import capture as dz_capture
from sources.dz_feed import decoder as dz_decoder


def test_decode_signature_matches_kalshi():
    sig = inspect.signature(dz_decoder.decode)
    assert list(sig.parameters) == ["raw", "t_arrival_ns"]


def test_stubs_raise_notimplemented():
    with pytest.raises(NotImplementedError):
        dz_decoder.decode(b"", 0)
    with pytest.raises(NotImplementedError):
        dz_capture.capture()
