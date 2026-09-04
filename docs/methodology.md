# Methodology — benchmarking the DoubleZero edge feed on Kalshi perps

This document states exactly what the latency benchmark measures, how, and why the numbers are fair. Every figure the project publishes is reproducible from this repository. Written to hold up to hostile scrutiny: if a claim here is wrong, the code contradicts it.

## What this measures

The **arrival-time delta of the same Kalshi crypto-perp trade delivered two ways to one host**:

- **Public baseline** — Kalshi's public perps WebSocket, the margin WS at `wss://external-api-margin-ws.kalshi.com` (`sources/kalshi_ws/`). The socket is API-key authenticated at the handshake; the `trade` channel is public.
- **Edge path** — the DoubleZero Kalshi edge multicast feed (`sources/dz_feed/`).

For each trade that appears on both feeds this is computed:

```
delta_ns = t_arrival(dz) − t_arrival(public)      # negative ⇒ DoubleZero delivered it first
```

The report is the **distribution** of `delta_ns` (p10 / p50 / p90 / p99, mean, min, max), the **win-rate** (share of trades DoubleZero delivered first), the **match rate**, and **discards** — never a single cherry-picked number.

## How the timing is done (and why it is fair)

1. **One host, one clock.** Both feeds are received on the *same* machine and each datagram is stamped on arrival with a single monotonic clock — `CLOCK_MONOTONIC_RAW` (`common/clock.py`). Timestamps taken on different machines are **never** compared, so there is no clock-skew or NTP error in the measurement. The delta is a difference of two readings from the *same* clock, which is exactly what a co-located consumer experiences.
2. **Stamp at the edge of the process.** Arrival is stamped the moment bytes are read from the socket, before any decoding, so decode cost is excluded from the delta and is identical for repeated runs.
3. **Same trade, matched by the venue's own fields.** The two feeds use **different trade-id spaces** — Kalshi's public `trade_id` is a UUID, the edge feed's is a `u64` — so ids cannot be compared directly. Instead each trade is matched by the fields the venue itself stamps and both feeds carry identically: **exchange execution timestamp (ms) + price + contract count**. The price is counted in the market's **own tick**, which the edge feed publishes in its instrument definitions: the two feeds reach the same price by different arithmetic, so the key has to round, and rounding to whole dollars — which this did until 2026-09-04 — collapses the price to `0` on DOGE, KSHIB, WLD and ADA and to `1` on XRP and SUI. Each trade on each side is matched at most once, live in `scripts/dz_latency_race.py` and on replay in `race/match.py`, so a single trade can never inflate the sample.
4. **One publisher arm, not both.** The multicast group is published twice over, by two hosts under two frame Channel IDs, carrying the same trades: one arrives ~5 ms ahead of the other, with real `u64` trade ids against the other's zeros. Taking both doubles every count and, on quotes, walks a book backwards whenever the slow copy of update *N* lands after the fast copy of *N+1* (measured 2026-09-04: 12.3% of quotes, 9.5% actually reverting bid/ask by 2–3 ms). The receivers therefore arbitrate: they watch the two arms race the same trade and keep the one that leads (`sources/dz_feed/arms.py`). The choice is taken **from the data**, never from a channel number, and is published in the output next to the counts it produced, so it can be checked rather than trusted. `--dz-channel N` forces one arm when you want to compare them.
5. **Distribution over a real window.** Numbers are reported over a capture spanning active *and* quiet periods (target ≥ 2 h, ≥ 500 matched pairs), not a hand-picked burst.
6. **The tails are published unclipped.** `p99`, `min` and `max` of the delta are reported as observed. They look implausible and are not: a −170 ms sample is the public socket stalling on a delivery (its own end-to-end max over the same window is 300 ms), and a +130 ms one is the reader process being descheduled between the kernel taking the packet and the monotonic stamp — which the delta charges to DoubleZero, against the side being advertised. Absolute figures *are* bounded (0–5000 ms) because there the wall clock can be stepped; a delta between two readings of one monotonic clock cannot be. Clipping it would remove exactly the tail the edge lives in.

## The two paths, stated plainly

- The public Kalshi perps WS is TCP + TLS over the public internet. Kalshi authenticates the socket at connect; authentication happens once at the handshake and is not on the per-message path, so it does not bias the per-trade delta.
- The DoubleZero feed is GRE-encapsulated UDP multicast delivered over DoubleZero's network and terminated on the `doublezero1` tunnel. On that tunnel a normal UDP multicast socket receives nothing, so the receiver taps the interface at the link layer via `AF_PACKET` and parses IP/UDP itself (`sources/dz_feed/capture.py`).

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
| Double-counting a trade | Each trade matched at most once, within a bounded time window |
| Decode cost skewing the delta | Arrival stamped before decode, on both feeds |
| Packet loss inflating "wins" | Sequence-gap check; gaps disclosed, reconnects logged |
| Feeds in different id spaces | Matched by exchange timestamp + price + size, not by trade id |

## Status

The harness, decoder, and self-check are complete and pass. Live edge-vs-public numbers require the Kalshi perps feed on DoubleZero and an access pass for the receiving host — an external dependency on the feed operator, not on this code. The moment the feed is available, the command above produces the numbers and this page's claims become measured, not asserted.
