# Kalshi Edge Lab — Design

**Date:** 2026-08-19
**Status:** Approved for planning
**Repo:** `hypnogaba/kalshi-edge-lab` (private)

This design refines the project's `SPEC.md`. Read `SPEC.md` for the full context and the plain-language plan. This document records the architecture and the decisions we made during brainstorming.

## 1. Goals

The project has three steps. We build A and B now; C is deferred and must not be built.

- **Step A — Latency Race.** One host, two pipes for the same BTCPERP market: the free public Kalshi WebSocket vs. the DoubleZero Edge feed, side by side, with a millisecond counter showing who sees each event first. Output: honest latency numbers + histogram/timeline PNG + a short recording + open code. No trading, no risk.
- **Step B — Demo Bot (primary).** A deliberately simple bot in the Kalshi DEMO environment (fake money). It builds the BTCPERP order book from our feed, compares it with Bitcoin price on Binance, and places demo orders when they diverge. The point is not profit; it is to show the full pipeline working: fast data in → decision → order out → live dashboard. Output: dashboard recording + forkable open-source code.
- **Step C — Live experiment.** Deferred. Real account, tiny real money, only after A+B land and Jared gives a separate written OK. Not specced, do not build.

## 2. Key insight: public Kalshi API is enough to build the whole bot now

Kalshi has a full public API (REST + WebSocket). Because of the source-adapter architecture below, the public Kalshi API is a fully valid data source for the bot. We build and demonstrate the **complete** demo bot now on public data, without waiting for the DZ feed, Ivan, or Jared.

The DZ feed is therefore not a precondition — it is an **upgrade**. When it arrives we swap one source adapter for a faster one and the same bot starts seeing the market earlier. The Latency Race measures exactly how much earlier.

### Kalshi API facts (verified 2026-08-19)

- **Public WebSocket channels:** `orderbook_delta` (snapshot + incremental deltas) and `trade`. These are the channels the race and the book builder consume.
- **Endpoints:** prod WS `wss://api.elections.kalshi.com/trade-api/ws/v2`; demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`. Demo Trade API root `https://external-api.demo.kalshi.co/trade-api/v2`.
- **Auth:** RSA signing on every request, even for public read channels. Three headers: `KALSHI-ACCESS-KEY` (Key ID), `KALSHI-ACCESS-TIMESTAMP` (ms), `KALSHI-ACCESS-SIGNATURE` (PSS/SHA256 over `timestamp + METHOD + path`, path without query string). So an API key is required even to read.
- **Demo account** is separate (sign up at `https://demo.kalshi.co/`, note `.co` not `.com`, email+password only). Its API keys are created in the demo account's profile settings, same flow as prod.

## 3. Architecture — source-adapter + normalized Event bus

Each **source** is an isolated adapter: a capture daemon (raw bytes → append-only disk) plus a decoder (raw → normalized `Event`). Everything downstream — race matching, book builder, bot, dashboard — only ever consumes `Event` streams and never knows which source produced them.

Adding the DZ feed later = implement two files under `sources/dz_feed/` (capture + decoder). Zero downstream changes.

Normalized event (per SPEC §0.4):

```
Event { source, t_arrival_ns, market, kind: trade|book_delta, price, size, side, seq_or_ids }
```

### Two ground rules baked into the architecture

1. **One clock, one host.** `common/clock.py` exposes `CLOCK_MONOTONIC_RAW`. Both captures stamp arrival with the same clock. We never compare timestamps across machines. The capture daemons and the race therefore run on the DZ-connected server (the only host that receives both streams); development and testing happen locally.
2. **DEMO only.** `bot/order_manager.py` physically contains no production trading endpoints. Hard-coded ceilings independent of config: max position, max orders/min, max daily paper loss, and a kill-switch file checked every loop.

## 4. Repo layout

```
kalshi-edge-lab/
  SPEC.md  README.md  pyproject.toml  Makefile  .env.example  .gitignore
  docs/            env.md  methodology.md  feed-notes.md  log.md  superpowers/{specs,plans}
  common/          event.py  clock.py  storage.py  config.py  ws_client.py
  sources/
    kalshi_ws/     capture.py  decoder.py          # real now
    dz_feed/       capture.py  decoder.py  README.md # stubs behind the interface, real later
  race/            match.py  stats.py  report.py  live_tui.py
  book/            builder.py  validate.py
  reference/       binance_ws.py
  bot/             signal.py  order_manager.py  guardrails.py  decision_log.py  run.py
  dash/            tui.py
  data/            # gitignored: raw captures, logs
  scripts/  tests/
```

Tooling: Python 3.12, `uv`, `ruff`, `pytest`. Makefile targets: `make capture | race | bot-demo | test`.

## 5. Data flow

```
Kalshi public WS ─┐
                  ├─ sources/*/capture.py → raw (t_arrival_ns, bytes) ─┐
DZ feed (later) ──┘                                                    │
                                                     sources/*/decoder.py → Event
                          ┌──────────────────────────────────┴───────────────┐
                          ▼                                                    ▼
                    race/ (Step A)                                    book/ + reference/ + bot/ (Step B)
              match → stats → report/live_tui             builder + binance_ws → signal → order_manager(DEMO) → decision_log → dash
```

## 6. Reuse from `hypnogaba/tradebot` (with rationale)

Copy code in (no dependency on the old repo), strip any keys/endpoints, record decisions in `docs/env.md`.

| From tradebot | Into | Why |
|---|---|---|
| `core/main.py` | capture + `bot/run.py` | Proven main-loop, graceful shutdown, reconnect skeleton |
| `core/config.py` | `common/config.py` | `.env` + config pattern already tested |
| `core/listener.py` | `common/ws_client.py` | WS reconnect/backoff reusable for Kalshi + Binance |
| `core/storage.py` | `common/storage.py` + `bot/decision_log.py` | Append-only file pattern the spec mandates |
| `execution/paper.py` | `bot/order_manager.py` | Paper order/fill/position tracking maps ~1:1 to Kalshi demo |
| `deploy/*` (systemd, deploy.sh, logrotate) | server run | Ready-made daemon deployment for the DZ box |

**Not reused** (Solana-specific per SPEC §0.2): all of `safety/` (rug/honeypot/helius), tx signing, slots/Jito/shreds, the sniping strategy, token scoring.

## 7. Building and proving without the DZ feed

Nothing is left unproven while we wait for Ivan:

- **Bot end-to-end:** runs fully on Kalshi public WS as the source + Binance reference → demo orders. Complete and demoable now.
- **Race harness:** exercised now by feeding it two public `Event` streams — Kalshi WS vs. a delayed replay of the same capture — to validate matching, stats, and the TUI. Real DZ-vs-WS numbers come once the feed adapter is done and both run on the server.

## 8. Signal v0 (deliberately naive, all params in one config)

Reference (Binance BTCUSDT perp `bookTicker`) mid moves > X bps within T seconds while the Kalshi mid lags → lean in the direction of the move. Explicitly labeled a dumb example; no profit claims anywhere.

## 9. Phases and acceptance criteria

- **Phase 0 — Plumbing.** Repo scaffold, tooling, `.env`/`.gitignore`, `common/` core, Kalshi WS capture + decoder, unit tests on captured samples. `docs/env.md` filled. Acceptance: 30 min clean Kalshi WS capture, reconnects logged, decoder tests pass.
- **Phase 1 — Latency Race.** `match.py`, `stats.py` (p10/p50/p90/p99, match rate, discards), `report.py` (histogram + timeline PNG), `live_tui.py` split-screen. `docs/methodology.md`. Acceptance: stats file + PNG + 20–40 s recording + methodology doc. **STOP for human review before anything public.**
- **Phase 2 — Book + Demo Bot.** `book/builder.py` (snapshot + deltas, gap resync) + `validate.py`; `reference/binance_ws.py`; `bot/` (signal, order_manager on demo REST, guardrails, decision_log); `dash/tui.py`. Acceptance: 24 h continuous demo run, zero crashes, complete decision log, recorded clip of a volatile window. **STOP for human review.**
- **Phase 3.** Not specced. Do not build.

## 10. Safety rails

- Repo stays **private** until Ivan + Jared review Step A output.
- Never commit: API keys, wallets, multicast/internal endpoints, or any DoubleZero-confidential format details not cleared for publication. `.env` + `.gitignore` from session 1.
- No profit promises anywhere. The bot is openly labeled a dumb example.
- No feed pricing, trial terms, or internal docs in the repo or posts.
- All order-placing code targets the Kalshi DEMO environment. Production trading endpoints must not appear in Phase 1–2 code paths.
- Every published number must be reproducible from code in this repo (`docs/methodology.md`).

## 11. Open dependencies from Ivan (do not block A/B on public data)

1. Feed wire-format doc — needed for `sources/dz_feed/decoder.py`; confirm what is publishable.
2. Exact multicast join procedure on the DZ server — needed for `sources/dz_feed/capture.py`.
3. Feed snapshot/recovery mechanism, or deltas-only?
4. Jared's written OK to publish measured latency numbers.

Available now: DZ-server access. Pending: the four items above + Kalshi demo/prod keys (user is creating them).

## 12. Empirical Kalshi access findings (verified 2026-08-19) + keyless REST adapter

Tested against live Kalshi to settle how we get real BTC data before a prod key exists:

| Access | Result |
|---|---|
| prod REST `/markets`, `/markets/{t}/orderbook`, `/markets/trades` — **no auth** | 200 (public) |
| prod **WebSocket** — no auth | 401 |
| prod **WebSocket** — demo key | 401 (demo key is not valid on the prod account) |
| demo env — any BTC market | volume=0, no order flow (sandbox has no trading) |

Consequences:
- The demo key **cannot** access the prod WS. Real-time streaming (and the Latency Race, which needs the public WS side) requires a **real prod read-only key** (a real kalshi.com account + KYC).
- prod REST is **public**, so real BTC **trades** are retrievable with no key. Real trade shape (REST): `{"trade_id","ticker","taker_side":"yes|no","yes_price_dollars":"0.0100","no_price_dollars":"0.9900","count_fp":"50.00","created_time"}` — prices are dollar strings, count is a float string. NOTE: this REST shape differs from the WS `trade` channel shape; the WS decoder paths remain pending prod-WS verification.
- prod REST **orderbook depth returns empty** in every sample (no-auth and demo-key alike), including markets with trade history and near-the-money strikes. Public REST reliably yields trades but not book depth; full depth needs the authenticated prod WS.

**Decision:** add a third source adapter, `sources/kalshi_rest/`, that polls the public prod REST and normalizes to `Event` — no key required. It reliably captures real BTC trade flow now (and book snapshots whenever depth is present). This lets Phase 2 (book/bot) develop against real prod trades immediately. The WS-based low-latency path and the Latency Race stay gated on a real prod key. Same `Event` interface, so nothing downstream changes when the WS/DZ sources come online.

`sources/kalshi_rest/` responsibilities: a public REST client, a `decoder` (REST orderbook + REST trade JSON → `Event`, converting dollar-string prices to integer cents and `count_fp` to int, dedup trades by `trade_id`), a `poller` (interval poll of selected markets → raw frames + Events), and a near-money market selector (pick strikes closest to the Binance BTC spot).

## 13. Venue confirmed: Kalshi over DoubleZero (with the DZ wire format)

The project's DoubleZero edge feed carries **Kalshi** market data. DoubleZero's value here is delivery speed: getting Kalshi data over the DZ edge multicast feed *faster than connecting directly to Kalshi's public API*. That is exactly what the Latency Race measures — **public Kalshi WS (direct) vs. DZ-edge Kalshi feed**, same host, millisecond delta.

The DZ feed uses the open **`edge-feed-spec`** binary wire format (Top-of-Book & Trades v3, fixed-size little-endian, GRE-encapsulated UDP multicast on `doublezero1`). That format is **venue-agnostic and explicitly supports prediction markets** — its `InstrumentDefinition` carries Asset Class `Prediction Binary/Scalar/Categorical` and Price Bound `Bounded [0,1] (binary outcomes)`. So the `sources/dz_feed/` decoder we built (verified byte-for-byte against the spec) is correct for the Kalshi feed unchanged; the `InstrumentDefinition` on the refdata port supplies Kalshi's symbols and price/qty exponents.

Note: the `malbeclabs/edge-multicast-ref` reference (group `tiredsolid`/`233.84.178.15`) used **Hyperliquid** as its *example* payload. That was a transport/format reference only — a brief Hyperliquid adapter built during exploration was **removed**. The project venue is Kalshi.

### What each side of the race uses
- **Direct baseline:** `sources/kalshi_ws/` — the public Kalshi WebSocket. Requires a Kalshi **prod** read-only key (Kalshi signs even public channels).
- **Fast path:** `sources/dz_feed/` — the DoubleZero Kalshi edge feed. Multicast group + ports are per-deployment (discover on the server via `doublezero multicast group list`); requires an access pass for the receiving IP and the `doublezero1` tunnel. No Kalshi key needed (it's DoubleZero's feed).
- **Runner:** `scripts/run_race.py` captures both on one host for N minutes and reports p10/p50/p90/p99 of `t_dz − t_public` (negative = DoubleZero faster) + a PNG. `--selfcheck` validates the compute path offline. See `docs/runbook.md`.

### Still needed from the operator (server-side, per-deployment)
1. The Kalshi feed's **multicast group + mktdata/refdata ports** (`doublezero multicast group list`).
2. An **access pass** for the receiving IP + the `doublezero1` tunnel up.
3. A Kalshi **prod read-only key** for the direct baseline (`KALSHI_PROD_KEY_ID` + `secrets/kalshi_prod_key.pem`).
(Optional, bot only: demo-account balance to place live paper orders.)
