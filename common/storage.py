"""Append-only binary frame log: (t_arrival_ns:u64, len:u32, payload)."""
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Self

_HEADER = struct.Struct("<QI")


class FrameWriter:
    def __init__(self, path: str | Path):
        self._f = open(path, "ab", buffering=0)  # noqa: SIM115 (kept open across writes)

    def write(self, t_arrival_ns: int, payload: bytes) -> None:
        self._f.write(_HEADER.pack(t_arrival_ns, len(payload)))
        self._f.write(payload)

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_frames(path: str | Path) -> Iterator[tuple[int, bytes]]:
    with open(path, "rb") as f:
        while True:
            header = f.read(_HEADER.size)
            if len(header) < _HEADER.size:
                return
            t, n = _HEADER.unpack(header)
            payload = f.read(n)
            if len(payload) < n:
                return
            yield t, payload
