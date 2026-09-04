"""Which publisher arm to believe, when the group carries more than one.

The Kalshi perps multicast group is published twice over, by two hosts with
different source IPs, carrying the SAME trades and quotes under two different
Channel IDs in the frame header. Measured on mainnet-beta 2026-09-03:

    channel 101   real u64 trade ids, earlier Source Timestamp   -- arrives first
    channel   1   trade id always 0,  Source Timestamp +1 ms     -- arrives ~5 ms later

They are NOT a symmetric A/B pair, and their Sequence Numbers live in separate
spaces, so a frame-level `(channel, seq)` dedup cannot see the duplication. A
reader that takes both gets every event twice: counters double, and a book
built from the merged stream is walked backwards every time the slow arm's copy
of update N lands after the fast arm's copy of update N+1 (measured: 12.3% of
quotes, of which 9.5% actually reverted bid/ask, by 2-3 ms).

So: arbitrate, don't merge. This picks the arm that is observed to lead and
drops the other, the way any feed handler arbitrates a redundant line.

The choice is made from the data, never hard-coded, because a channel number is
a property of DoubleZero's deployment and not of us: pinning to the value that
happened to be fast on the day would silently start measuring the slow arm the
moment they swap. Trades seen on two channels with identical (market, price,
size) inside `pair_ttl_ns` are one trade; the channel that got there first wins
that pair, and the arm with the most wins over the last `keep` pairs is
selected. `--dz-channel N` forces a specific one when you need to compare.

Everything the choice rests on is published in `stats()`, so a reader can check
the arbitration instead of trusting it.
"""
from __future__ import annotations

import threading
from collections import Counter, deque

# Enough pairs that one lucky packet cannot decide it, few enough that the
# warm-up is seconds at the ~5 trades/s this feed runs at.
_MIN_PAIRS = 10
# Two sightings of the same (market, price, size) further apart than this are
# two different trades, not two copies of one.
_PAIR_TTL_NS = 2_000_000_000
# If the selected arm goes quiet this long while another arm is still live, the
# selection is dropped and made again. Without this, pinning to an arm that
# DoubleZero later retires would silence the whole feed.
_SILENCE_NS = 5_000_000_000
_KEEP_PAIRS = 500


class ArmArbiter:
    """Decides which frame Channel ID to accept; drops the duplicate arm."""

    def __init__(self, forced: int | None = None, *, min_pairs: int = _MIN_PAIRS,
                 pair_ttl_ns: int = _PAIR_TTL_NS, silence_ns: int = _SILENCE_NS,
                 keep: int = _KEEP_PAIRS) -> None:
        self._lock = threading.Lock()
        self._forced = forced
        self._min_pairs = min_pairs
        self._pair_ttl_ns = pair_ttl_ns
        self._silence_ns = silence_ns
        self._selected: int | None = forced
        self._pending: dict[tuple, tuple[int, int]] = {}   # key -> (channel, arrival_ns)
        self._outcomes: deque[tuple[int, int, int]] = deque(maxlen=keep)  # win, lose, lag_ns
        self._frames: Counter[int] = Counter()
        self._trades: Counter[int] = Counter()
        self._dropped: Counter[int] = Counter()
        self._wins_total: Counter[int] = Counter()
        self._last_seen: dict[int, int] = {}
        self._pairs = 0
        self._stale_pairs = 0
        self._reselections = 0

    # -- ingest ---------------------------------------------------------------
    def note_frame(self, channel: int, arrival_ns: int) -> None:
        with self._lock:
            self._frames[channel] += 1
            self._last_seen[channel] = arrival_ns

    def observe_trade(self, channel: int, key: tuple, arrival_ns: int) -> None:
        """One arm's sighting of a trade. `key` must be the venue's own values
        (market, price, size), which both arms carry identically -- NOT the
        Source Timestamp, which the slow arm shifts by a millisecond, nor the
        trade id, which it publishes as 0."""
        with self._lock:
            self._trades[channel] += 1
            self._sweep(arrival_ns)
            prev = self._pending.get(key)
            if prev is None:
                self._pending[key] = (channel, arrival_ns)
                return
            prev_channel, prev_ns = prev
            if prev_channel == channel:
                return  # same arm again: keep the earliest sighting, wait for the twin
            if arrival_ns - prev_ns > self._pair_ttl_ns:
                # Too far apart to be one trade. Two prints at the same price and
                # size half a minute apart are two trades, and pairing them
                # invents a lag of half a minute and hands the wrong arm a win.
                # Seen live: a 40 s "lag" in the published statistic on day one.
                self._pending[key] = (channel, arrival_ns)
                self._stale_pairs += 1
                return
            del self._pending[key]
            self._pairs += 1
            self._wins_total[prev_channel] += 1
            self._outcomes.append((prev_channel, channel, arrival_ns - prev_ns))
            self._resolve()

    def _sweep(self, now_ns: int) -> None:
        """Drop sightings whose twin never came, so the map cannot grow without
        bound in a process that runs for days. Correctness does not rest on this
        running often: the age of a sighting is checked again when it pairs."""
        if len(self._pending) < 256:
            return
        cutoff = now_ns - self._pair_ttl_ns
        for k in [k for k, v in self._pending.items() if v[1] < cutoff]:
            del self._pending[k]

    def _resolve(self) -> None:
        """Caller holds the lock. Pick the arm that leads over the recent window."""
        if self._forced is not None or len(self._outcomes) < self._min_pairs:
            return
        wins: Counter[int] = Counter(w for w, _l, _lag in self._outcomes)
        best, _count = wins.most_common(1)[0]
        if best != self._selected:
            if self._selected is not None:
                self._reselections += 1
            self._selected = best

    # -- decide ---------------------------------------------------------------
    def accepts(self, channel: int, now_ns: int) -> bool:
        """True if this frame's events should reach the book/matcher."""
        with self._lock:
            if self._forced is not None:
                accept = channel == self._forced
            elif self._selected is None:
                accept = True   # warm-up: no worse than taking everything, which is what we did
            else:
                last = self._last_seen.get(self._selected, 0)
                if now_ns - last > self._silence_ns:
                    # the arm we picked has gone quiet; re-open the choice
                    self._selected = None
                    self._outcomes.clear()
                    self._reselections += 1
                    accept = True
                else:
                    accept = channel == self._selected
            if not accept:
                self._dropped[channel] += 1
            return accept

    @property
    def selected(self) -> int | None:
        with self._lock:
            return self._selected

    # -- publish --------------------------------------------------------------
    def stats(self, now_ns: int = 0) -> dict:
        with self._lock:
            channels = {}
            for ch in sorted(set(self._frames) | set(self._trades)):
                row = {"frames": self._frames[ch], "trades": self._trades[ch],
                       "wins": self._wins_total[ch], "dropped_frames": self._dropped[ch]}
                if now_ns and ch in self._last_seen:
                    row["last_seen_ms_ago"] = round((now_ns - self._last_seen[ch]) / 1e6, 1)
                channels[str(ch)] = row
            lags = sorted(lag for _w, _l, lag in self._outcomes)
            out = {
                "mode": "forced" if self._forced is not None else "auto",
                "selected": self._selected,
                "pairs": self._pairs,
                "stale_pairs": self._stale_pairs,
                "reselections": self._reselections,
                "channels": channels,
            }
        if lags:
            def at(q: float) -> float:
                return round(lags[min(len(lags) - 1, int(len(lags) * q))] / 1e6, 3)
            out["loser_lag_ms"] = {"n": len(lags), "p10": at(0.10), "p50": at(0.50),
                                   "p90": at(0.90), "p99": at(0.99),
                                   "max": round(lags[-1] / 1e6, 3)}
        return out
