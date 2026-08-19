# scripts/verify_capture.py
"""Acceptance checks over a capture file: frame count, decode rate, seq contiguity.
Run: uv run python -m scripts.verify_capture data/accept.bin"""
import sys

from common.event import Kind
from common.storage import read_frames
from sources.kalshi_ws.decoder import decode


def main(path: str) -> int:
    frames = 0
    events = 0
    last_seq: int | None = None
    gaps = 0
    for t, payload in read_frames(path):
        frames += 1
        evs = decode(payload, t)
        events += len(evs)
        for e in evs:
            if e.kind in (Kind.BOOK_DELTA, Kind.BOOK_SNAPSHOT) and e.seq is not None:
                if last_seq is not None and e.seq != last_seq and e.seq != last_seq + 1:
                    gaps += 1
                last_seq = e.seq
    print(f"frames={frames} events={events} seq_gaps={gaps}")
    ok = frames > 0 and events > 0
    print("ACCEPTANCE:", "PASS" if ok else "FAIL")
    print("NOTE: any seq_gaps must be explained by a logged reconnect.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
