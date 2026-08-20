# kalshi-edge-lab

Benchmark and consume the DoubleZero Kalshi edge feed. It measures whether
DZ's multicast market-data feed delivers Kalshi trades faster than the
public internet, and ships a small demo bot that trades on the normalized
event stream.

## What's here

- `scripts/run_race.py` — the latency benchmark. Captures the public Kalshi
  WS and the DZ edge feed on one host at once, matches trades between them,
  and reports the arrival-time delta (`t_dz - t_public`).
- `bot/` — a reference demo bot: polls Kalshi + Binance, runs a naive signal
  through guardrails, and places Kalshi **DEMO** orders (no real money).
- `sources/dz_feed/` — an open binary decoder for the DoubleZero edge feed,
  verified against `edge-feed-spec`. `sources/kalshi_ws/` and
  `sources/kalshi_rest/` are the public Kalshi adapters (WS + REST). All
  three normalize into one `common/event.py` `Event`.

## Quickstart (laptop, no feed/keys)

```bash
uv sync
uv run pytest -q
uv run python -m scripts.run_race --selfcheck   # validates the matcher/stats offline
```

## Run the real latency race (server)

The DZ edge feed only arrives on a Linux host connected to DoubleZero — a
laptop can't join that multicast group, so the real race has to run there.
See `deploy/README.md` and `docs/runbook.md` for setup. Once the host is
wired up:

```bash
MARKET=<kalshi_ticker> GROUP=<mcast> IFACE=<recv_ip> bash deploy/run_race.sh
```

## Layout

```
common/       Shared Event type, config, storage (frame log), clock, WS client
sources/
  kalshi_ws/  Public Kalshi WebSocket adapter (capture + decode)
  kalshi_rest/ Public Kalshi REST adapter (poller + decode, no key needed)
  dz_feed/    DoubleZero edge feed: UDP multicast capture + binary decoder
race/         Trade matcher, latency stats, report rendering, live TUI
bot/          Reference demo bot: signal, guardrails, order manager, decision log
dash/         Dashboard TUI / HTML portal for race and bot output
scripts/      CLI entry points (run_race, discover_markets, verify_capture, check_auth)
deploy/       Server setup + run scripts for the DZ-connected host
docs/         Runbook, env reference, feed notes
```

## Data & wire format

The DZ feed uses the open `edge-feed-spec` Top-of-Book & Trades v3 binary
format (https://github.com/malbeclabs/edge-feed-spec); public Kalshi is
consumed via WS (prod key required) and REST (keyless).

## Safety

Order-placing code is demo-only; never commit `.env`, `secrets/`, or `data/`.
