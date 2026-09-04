# Kalshi Perps · DoubleZero

Consume and benchmark the DoubleZero edge feed of Kalshi crypto perpetuals: an open binary
decoder for the feed, plus a single-clock benchmark of how much sooner it delivers each trade
than Kalshi's public perps WebSocket.

![CI](https://github.com/hypnogaba/kalshi-edge-lab/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)

## What this is

The DoubleZero edge network delivers Kalshi crypto-perp market data — top-of-book quotes and
trades — as binary UDP multicast. This repository decodes that feed and benchmarks its latency
against Kalshi's own public perps WebSocket (`external-api-margin-ws.kalshi.com`). Both feeds
are received on one host, matched trade-for-trade, and timed against a single clock, so the
result is the arrival advantage a co-located consumer actually gets.

## The benchmark

The same trade is received two ways on one machine and timed with one monotonic clock
(`CLOCK_MONOTONIC_RAW`), stamped at the moment bytes leave the socket, before any decoding.
Because the two feeds live in different trade-id spaces (Kalshi's public `trade_id` is a UUID,
the edge feed's is a `u64`), each trade is matched by the venue's own execution timestamp, price
and size — identical on both sides. The price is counted in the market's own tick, which the
edge feed publishes in its instrument definitions, because the two sides reach the same price by
different arithmetic. The metric is:

```
delta = t_arrival(dz) − t_arrival(public)      # negative ⇒ DoubleZero delivered it first
```

The headline figures are **win-rate** (share of trades where DoubleZero arrived first) and
**median lead**. Alongside the lead, the dashboard reports the **absolute** trip: every Kalshi
trade carries the venue's own execution timestamp, so the clock can start at the exchange rather
than at our door, and each feed's end-to-end time is reported over the same matched trades.

Live numbers are shown on the dashboard and are reproducible from source; they are not
hard-coded here. Full method, threats to validity, and offline tool validation are in
[`docs/methodology.md`](docs/methodology.md).

### One publisher, not two

The multicast group is published twice over, from two hosts under two frame Channel IDs,
carrying the same trades a few milliseconds apart. A reader that takes both counts everything
twice and, on quotes, walks its book backwards whenever the slow copy of an update lands after
the fast copy of the next one. So the receivers arbitrate: they watch the arms race the same
trade and keep the one that leads. The choice is made from the data rather than from a channel
number, and is published next to the counts it produced. See
[`sources/dz_feed/arms.py`](sources/dz_feed/arms.py).

## Live dashboard

[`web/server.py`](web/server.py) is a read-only FastAPI + SSE app serving two self-contained,
monochrome pages. It never places orders or touches funds.

- `/` — the benchmark: how much sooner the data arrives, and how long the trip takes, plus the
  live decoded feed for every Kalshi crypto perpetual.
- `/duel` — the demo: what that head start actually buys.

```bash
uv run python -m web.server        # http://localhost:8080
```

The pages read JSON snapshots written by collector services on the DoubleZero-connected host:

- [`scripts/dz_live_feed.py`](scripts/dz_live_feed.py) — decoded feed → `data/dz_feed_state.json`
- [`scripts/dz_latency_race.py`](scripts/dz_latency_race.py) — live race → `data/dz_latency.json`
- [`demo/runner.py`](demo/runner.py) — the two-bot duel → `data/demo_state.json`

## The duel

[`demo/`](demo/) runs **one strategy twice**, one copy fed by the edge feed and one by the public
WebSocket, in a single process on a single clock. Both react to the same print, both are filled
against the same order book, and each is judged at the moment its own order could have arrived.
The only difference between them is when they found out.

The honest claim it supports is that you **get the price you aimed at more often**, which is what
the fill rates measure. It is not a claim that faster is more profitable: the demo rule crosses
the spread on purpose, so its mark-out is negative for both copies. Fills are paper, model no
queue position and no fees, and both sides get that same free pass. What to show and what not to
claim is in [`docs/stream-runbook.md`](docs/stream-runbook.md).

## The feed & decoder

The feed is GRE-encapsulated UDP multicast delivered over DoubleZero and terminated on the
`doublezero1` tunnel interface. Its wire format is the open
[**Top-of-Book & Trades v3**](https://github.com/malbeclabs/edge-feed-spec) binary protocol —
fixed-size, little-endian frames. [`sources/dz_feed/`](sources/dz_feed/) decodes it and is
verified byte-for-byte against that spec.

One operational note: on the DoubleZero tunnel a normal UDP multicast socket receives nothing,
so capture taps the interface at the link layer via `AF_PACKET` (`--link doublezero1`) and
parses IP/UDP itself. See [`sources/dz_feed/capture.py`](sources/dz_feed/capture.py).

## Quickstart

No feed access or keys are needed for the offline path:

```bash
uv sync
uv run pytest -q
uv run python -m scripts.run_race --selfcheck   # offline wiring proof (recovers +3.000 ms)
```

The self-check feeds the matcher one synthetic stream and a copy delayed by a known +3 ms, and
confirms the tooling recovers exactly +3.000 ms at a 100% match rate.

## Layout

```
common/          Event, clock, storage, config, reconnecting WS client
sources/
  dz_feed/       Edge feed: AF_PACKET capture, binary decoder, instrument registry,
                 publisher-arm arbitration, per-market contract size and tick
  kalshi_ws/     Public Kalshi perps WebSocket adapter (capture + decode)
race/            Trade matcher, latency stats, PNG report
demo/            Two-bot duel: one strategy, two feeds, shared order book
scripts/         run_race, dz_live_feed, dz_latency_race, check_auth, verify_capture
web/             Live dashboard and duel page (FastAPI + SSE)
deploy/          Server setup, run scripts, systemd units, tunnel guide
docs/            Methodology, runbook, stream runbook, feed notes
tests/           Decoder, matcher, arbitration, stats, duel, and pipeline tests
```

## Reproducibility & methodology

Every published latency figure is reproducible from this repository. The measurement method,
what it deliberately does not clip, and its threats to validity are in
[`docs/methodology.md`](docs/methodology.md). Server-side operation for the live race is in
[`docs/runbook.md`](docs/runbook.md), the public perps WS field notes in
[`docs/feed-notes.md`](docs/feed-notes.md).

[`scripts/run_race.py`](scripts/run_race.py) is the capture-then-replay twin of the live race:
it records both feeds to disk and matches them offline, using the same socket, the same
publisher-arm arbitration and the same join key, so a run can be re-examined after the fact.

## License

[Apache-2.0](LICENSE).
