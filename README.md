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
the edge feed's is a `u64`), each trade is matched by the venue's own execution timestamp plus
price plus size — identical on both sides. The metric is:

```
delta = t_arrival(dz) − t_arrival(public)      # negative ⇒ DoubleZero delivered it first
```

The headline figures are **win-rate** (share of trades where DoubleZero arrived first) and
**median lead**. Live numbers are shown on the dashboard and are reproducible from source; they
are not hard-coded here. Full method, threats to validity, and offline tool validation are in
[`docs/methodology.md`](docs/methodology.md).

## Live dashboard

[`web/server.py`](web/server.py) is a read-only FastAPI + SSE app that serves a self-contained,
monochrome page: a live latency scoreboard plus the live decoded feed for every Kalshi crypto
perpetual. It never places orders or touches funds.

```bash
uv run python -m web.server        # http://localhost:8080
```

The page reads two JSON snapshots written by two collector services that run on the
DoubleZero-connected host:

- [`scripts/dz_live_feed.py`](scripts/dz_live_feed.py) — decoded feed → `data/dz_feed_state.json`
- [`scripts/dz_latency_race.py`](scripts/dz_latency_race.py) — live race → `data/dz_latency.json`

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
  dz_feed/       DoubleZero edge feed: AF_PACKET capture + binary decoder + registry
  kalshi_ws/     Public Kalshi perps WebSocket adapter (capture + decode)
race/            Trade matcher, latency stats, PNG report
scripts/         run_race, dz_live_feed, dz_latency_race, check_auth, verify_capture
web/             Live web dashboard (FastAPI + SSE)
deploy/          Server setup, run scripts, systemd units, tunnel guide
docs/            Methodology, runbook, feed notes
tests/           Decoder, matcher, stats, and pipeline tests
```

## Reproducibility & methodology

Every published latency figure is reproducible from this repository. The measurement method
and its validation are in [`docs/methodology.md`](docs/methodology.md); the server-side
operation for running the live race is in [`docs/runbook.md`](docs/runbook.md).

## License

[Apache-2.0](LICENSE).
