"""DoubleZero Edge feed decoder — STUB.
Implement once the wire-format doc arrives. See sources/dz_feed/README.md.
Must return list[Event] with the same contract as sources/kalshi_ws/decoder.decode."""
from common.event import Event


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    raise NotImplementedError(
        "DZ feed decoder not implemented — needs the wire-format doc from Ivan. "
        "See sources/dz_feed/README.md.")
