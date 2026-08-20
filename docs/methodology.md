# Methodology — measuring the DoubleZero edge on Kalshi

This document states exactly what the latency benchmark measures, how, and why the numbers are fair. Every figure the project publishes is reproducible from this repository. Written to hold up to hostile scrutiny: if a claim here is wrong, the code contradicts it.

## What this measures

The **arrival-time delta of the same Kalshi market event delivered two ways to one host**:

- **Direct baseline** — the public Kalshi WebSocket (`sources/kalshi_ws/`).
- **Fast path** — the DoubleZero Kalshi edge multicast feed (`sources/dz_feed/`).

For each event that appears on both feeds this is computed:

```
delta_ns = t_arrival(dz) − t_arrival(public)      # negative ⇒ DoubleZero delivered it first
```

The report is the **distribution** of `delta_ns` (p10 / p50 / p90 / p99, mean, min, max), the **match rate**, and **discards** — never a single cherry-picked number.

## How the timing is done (and why it is fair)

1. **One host, one clock.** Both feeds are received on the *same* machine and each datagram is stamped on arrival with a single monotonic clock — `CLOCK_MONOTONIC_RAW` (`common/clock.py`). Timestamps taken on different machines are **never** compared, so there is no clock-skew or NTP error in the measurement. The delta is a difference of two readings from the *same* clock, which is exactly what a co-located consumer experiences.
2. **Stamp at the edge of the process.** Arrival is stamped the moment bytes are read from the socket, before any decoding, so decode cost is excluded from the delta and is identical for repeated runs.
3. **Same market, same event.** The *same* trade is matched across the two feeds:
   - **Primary key: exact trade id.** Both feeds carry the venue trade id (`Event.seq`); an id match is unambiguous.
   - **Fallback:** same market + equal price and size, nearest-in-time within a bounded window (`--window-ms`, default 50 ms). Each event on each side is matched at most once (`race/match.py`), so a single event can never inflate the sample.
4. **Distribution over a real window.** Numbers are reported over a capture spanning active *and* quiet periods (target ≥ 2 h, ≥ 500 matched pairs), not a hand-picked burst.

## The two paths, stated plainly

- The public Kalshi WS is TCP + TLS over the public internet. Kalshi authenticates the socket (it signs even public channels); authentication happens once at connect and is not on the per-message path, so it does not bias the per-event delta.
- The DoubleZero feed is GRE-encapsulated UDP multicast delivered over DoubleZero's network and terminated on the `doublezero1` tunnel; the kernel de-encapsulates GRE so the application reads plain UDP. The receiver is `sources/dz_feed/capture.py`.

These are genuinely different transports — that is the point of the comparison. This is not normalized away; the measurement is of what a consumer actually gets from each.

## Reproducibility

- The whole pipeline is in this repo. Re-run:
  ```bash
  MARKET=<kalshi_ticker> GROUP=<mcast> IFACE=<recv_ip> bash deploy/run_race.sh
  ```
  It writes the raw captures, `data/race/race_stats.json`, and `data/race/race.png`.
- The DoubleZero decoder is verified **byte-for-byte** against the open [`edge-feed-spec`](https://github.com/malbeclabs/edge-feed-spec) Top-of-Book & Trades v3 wire format, with unit tests over constructed frames (`tests/test_dz_decoder.py`).
- Frame **sequence numbers** are contiguous per channel; any gap must be explained by a logged reconnect (`scripts/verify_capture.py`). Unexplained gaps are treated as packet loss and disclosed, not hidden.

## Tool validation (independent of any live feed)

The matcher and statistics are validated offline, so the measurement instrument is proven before it is pointed at real feeds:

```bash
uv run python -m scripts.run_race --selfcheck
# 50/50 matched (100.0%) · p50 delta recovered +3.000 ms  → SELFCHECK: PASS
```

The self-check feeds the pipeline one stream and a copy of it delayed by a known **+3 ms**, and confirms the tooling recovers exactly +3.000 ms at 100% match. If the matcher or percentile code were wrong, this would not pass.

## Threats to validity (and how they are handled)

| Concern | Handling |
|---|---|
| Clock skew between machines | Eliminated — single host, single monotonic clock |
| Cherry-picked window | Report a distribution over a long window spanning active + quiet |
| Double-counting an event | Each event matched at most once; primary key is the exact trade id |
| Decode cost skewing the delta | Arrival stamped before decode, on both feeds |
| Packet loss inflating "wins" | Sequence-gap check; gaps disclosed, reconnects logged |
| Feeds carrying different data | Both derive from the same Kalshi book; matched per-trade by id |

## Status

The harness, decoder, and self-check are complete and pass. **Live edge-vs-public numbers are pending the Kalshi feed being published on DoubleZero and an access pass for the receiving host** — that is an external dependency on the DoubleZero feed operator, not on this code. The moment the feed is available, the command above produces the numbers and this page's claims become measured, not asserted.

## No claims that can't be backed

No profit is claimed anywhere. The demo bot's signal is an openly labelled naïve example. The only quantitative claim this project will make is the measured latency distribution above, reproducible by anyone with the same repo and feed access.
