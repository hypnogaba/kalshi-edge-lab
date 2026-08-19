# Hyperliquid Edge — Implementation Plan (DZ feed + public WS + latency race)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Bring the project onto its true venue — Hyperliquid over the DoubleZero edge feed. Build (1) a public Hyperliquid WS adapter, (2) a real DZ Top-of-Book & Trades binary decoder + multicast subscriber, and (3) the latency race that compares them. Same `Event` bus and source-adapter architecture as the existing Kalshi work.

**Why:** The DoubleZero edge feed is Hyperliquid market data (confirmed: `malbeclabs/edge-multicast-ref`, `malbeclabs/edge-feed-spec`). `BTCPERP` = HL BTC perpetual. The Kalshi adapters remain as a second source; the flagship latency proof runs on Hyperliquid.

**Runs where:** hl_ws + race harness are testable now (Mac). The DZ multicast subscriber runs on the user's DZ-connected server (GRE `doublezero1`, access pass per IP); its decoder is unit-tested locally against constructed frames.

## Verified references
- DZ transport: GRE-encapsulated UDP multicast; kernel decaps → clean UDP on `doublezero1`. Group `tiredsolid` → **233.84.178.15**, mainnet-beta, `source_id=1`, MBO `channel_id=1`. Two-port model per channel: **mktdata** (Quote/Trade/Heartbeat/EndOfSession) + **refdata** (InstrumentDefinition/ManifestSummary). Port sets — A: TOB 9601/9602; B: 9801/9802; C: 9101/9102 (mktdata/refdata). MBO ports 106xx/108xx/101xx.
- Wire (Top-of-Book & Trades v3, little-endian, fixed-size). Full spec: `github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md` — the DZ-decoder task MUST read it for exact byte offsets of Trade/Heartbeat/EndOfSession.
  - **Frame header (24B):** `0` Magic u16 `0x445A`; `2` Schema Ver u8 (=3); `3` Channel ID u8; `4` Seq u64; `12` Send ts_ns u64; `20` Msg Count u8; `21` Reset Count u8; `22` Frame Length u16.
  - **App msg header (4B):** `0` Type u8; `1` Length u8; `2` Flags u16 (bit0 = snapshot).
  - **Quote 0x03 (60B):** `4` InstrumentID u32; `8` SourceID u16; `10` UpdateFlags u8; `12` Source ts_ns u64; `20` Bid Price i64; `28` Bid Qty u64; `36` Ask Price i64; `44` Ask Qty u64; `52` Bid Src Count u16; `54` Ask Src Count u16.
  - **Trade 0x04 (52B):** `4` InstrumentID u32; `8` SourceID u16; `10` Aggressor Side u8 (1=Buy,2=Sell,0=Unknown); remaining fields (Trade ID, Price i64, Qty u64, Source ts_ns) — READ FROM SPEC for exact offsets.
  - **InstrumentDefinition 0x02 (130B, refdata):** `4` InstrumentID u32; `8` SourceID u16; `10` Symbol char[64]; `90` Asset Class u8; `91` Price Exponent i8; `92` Qty Exponent i8; ... Prices/qtys use per-instrument exponents (raw i64/u64 × 10^exponent).
- Public Hyperliquid WS: `wss://api.hyperliquid.xyz/ws`. Subscribe `{"method":"subscribe","subscription":{"type":"trades","coin":"BTC"}}` and `{"type":"bbo","coin":"BTC"}`. Trade: `{"channel":"trades","data":[{"coin","side":"B"|"A","px":"..","sz":"..","time":ms,"tid":int}]}`. BBO: `{"channel":"bbo","data":{"coin","time":ms,"bbo":[{"px","sz","n"}(bid),{"px","sz","n"}(ask)]}}`.

## Task 0: generalize `common/event.py` (additive, non-breaking)
- Add `Kind.QUOTE = "quote"`.
- Add to `Side`: `BID="bid"`, `ASK="ask"`, `BUY="buy"`, `SELL="sell"` (keep YES/NO).
- Allow decimal prices/sizes: annotate `price: int | float | None`, `size: int | float | None` (runtime unchanged; existing Kalshi int usage unaffected).
- Existing tests must still pass (additive change). Commit.

## Task 1: `sources/hl_ws/` — public Hyperliquid adapter (testable now)
- `sources/hl_ws/__init__.py`, `decoder.py`, `capture.py`.
- `decoder.decode(raw, t_arrival_ns) -> list[Event]`: HL trades → `Event(source=HL_WS, kind=TRADE, price=float(px), size=float(sz), side=BUY if "B" else SELL, seq=tid)`; HL bbo → two `Event(kind=QUOTE, side=BID/ASK, price, size)` sharing `seq=time`. Add `Source.HL_WS="hl_ws"`.
- `capture.py`: subscribe trades+bbo for a coin via `common.ws_client.ReconnectingWS`; stamp `now_ns()`; write raw frames (envelope with channel) via `FrameWriter`; `--coin BTC --minutes N --out`.
- TDD the decoder against the real sample messages above; live smoke: 30s capture of BTC → nonzero frames, decode → trade + quote events. Commit per step.

## Task 2: `sources/dz_feed/decoder.py` — real Top-of-Book decoder
- Replace the stub. `decode(raw: bytes, t_arrival_ns) -> list[Event]`: parse the 24B frame header (verify magic `0x445A`, schema 3; else return []), then iterate `Msg Count` app messages by `Message Length`. Decode Quote 0x03 → two `Event(kind=QUOTE, side=BID/ASK, source=DZ_FEED, seq=frame.seq)`; Trade 0x04 → `Event(kind=TRADE, side=BUY/SELL)`; InstrumentDefinition 0x02 → update an instrument registry (ID→symbol, price_exp, qty_exp) and return []. Apply exponents: `price = raw_i64 * 10**price_exp`, `size = raw_u64 * 10**qty_exp` (needs the instrument's exponents; if unknown yet, keep raw + mark). Skip unknown types via Message Length.
- `sources/dz_feed/registry.py`: InstrumentID → InstrumentDefinition (symbol/exponents), fed by 0x02 messages.
- READ the full top-of-book spec from GitHub for exact Trade/Heartbeat/EOS offsets before coding.
- TDD: build byte frames in the test (a small frame encoder helper) covering a Quote, a Trade, and an InstrumentDefinition, and assert decoded Events (with exponent scaling). Commit.

## Task 3: `sources/dz_feed/capture.py` — multicast subscriber (server-run)
- Replace the stub. Join the multicast group (default `233.84.178.15`) on a given interface (`doublezero1`) binding BOTH mktdata + refdata ports (port set configurable, default A: 9601/9602). Stamp `now_ns()` per datagram, write raw `(t_arrival_ns, bytes)` frames. `--group --mktdata-port --refdata-port --iface --minutes --out`.
- Use `socket` with `IP_ADD_MEMBERSHIP` (and `SO_REUSEADDR`); one socket per port, `select`/asyncio to read both. Document that GRE decap is handled by the DZ client (kernel) so the app sees plain UDP.
- Not live-testable locally (no feed); provide a `--selftest` that loopback-sends a constructed frame to verify the receive+write path. Commit.

## Task 4: `race/` — latency race
- `race/match.py`: given two decoded `Event` streams (each `(t_arrival_ns, Event)`), match TRADES across sources by `(instrument/coin, price, size, nearest-in-time within window)`; where both carry a trade id (`seq`), prefer exact id match. Emit `delta_ns = t_arrival_dz - t_arrival_public` per matched pair (sign = who was first). Secondary: QUOTE top-of-book change to the same new BBO.
- `race/stats.py`: p10/p50/p90/p99, mean, match rate, discards, count. Pure + TDD.
- `race/report.py`: render histogram + timeline (matplotlib) to PNG.
- `race/live_tui.py`: split-screen rich TUI — left public WS BBO, right DZ feed BBO, running delta counter.
- Dev/validation now: feed the matcher two public HL WS streams (or WS vs delayed replay) to prove matching+stats end-to-end; real numbers once the DZ feed runs on the server. TDD stats/match; commit per step.

## Definition of Done
- hl_ws adapter live-verified (real BTC trades + BBO → Events).
- dz_feed decoder unit-tested against constructed v3 frames (Quote/Trade/InstrumentDefinition, exponent scaling); multicast subscriber self-test passes.
- race match+stats unit-tested; TUI + report render.
- `pytest` + `ruff` green. Same `Event` contract throughout.
