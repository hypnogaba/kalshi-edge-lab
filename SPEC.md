# Kalshi x DoubleZero Edge Lab
## Latency Race + Demo Trading Bot - Project Plan & Spec

This document has two parts.
**Part 1** is the plan in plain words - for Ivan and anyone at DoubleZero who wants to understand the project.
**Part 2** is the technical spec - for Claude Code to execute. If you are Claude Code: read Part 1 for context, then work strictly from Part 2.

---

# PART 1 - THE PLAN IN PLAIN WORDS

## What we are building and why

Traders don't apply for our Kalshi feed because they can't see what it gives them. Nobody has shown them the difference. So we will show it - publicly, honestly, with real numbers - in three steps, each producing something Ivan can post on Twitter and the company can reuse.

**Step A - The Latency Race.** One server, two pipes: the same Kalshi market (BTCPERP) coming in through the free public Kalshi WebSocket and through our Edge feed, side by side on one screen, with a millisecond counter showing who sees each trade first. Output: a short video/GIF + a table of honest numbers + open code. This is "stop telling, start showing." No trading involved, no risk, nothing to approve except the numbers themselves.

**Step B - The Demo Bot.** A deliberately simple trading bot running in Kalshi's DEMO environment (fake money, zero risk). It watches Bitcoin price on a big crypto exchange, compares it with the Kalshi BTCPERP order book coming from our feed, and places demo orders when they diverge. The point is not profit - the point is showing the full pipeline working: fast data in, decision, order out, live dashboard. Output: a screen recording of the dashboard + open-source code others can fork and put their own strategy into.

**Step C - Live experiment (maybe, later).** Real account, tiny real money, documented publicly. Only if A and B land well and Jared gives a separate OK. We decide this later, not now.

## What this gives us

1. The missing "proof" content: a benchmark nobody can argue with, because the code is open and the method is clean.
2. A starter kit: the exact thing our research said traders need - a way to see the value instead of guessing.
3. A build-in-public story for Ivan's Twitter that fits his voice and reaches crypto traders - the same crowd that ignored the press-release-style announcement.
4. Internal credibility: "the support guy measured it and built it."

## What is needed from Ivan (the full list)

Before coding starts:
1. **Feed documentation** - ask Greg or Jared for the wire-format spec of the Kalshi feed (the document that describes what the messages look like) and confirm which part of it, if any, is OK to reference in public code.
2. **Multicast details** - the exact group/subscription info to receive the Kalshi feed on your server (whoever set up your feed access has this).
3. **Server access** - Claude Code needs to work on the DZ-connected server where the feed arrives.
4. **Kalshi API keys** - create one for the demo environment (needed in Step B) and a read-only one for production data (Step A). Takes 10 minutes on kalshi.com.
5. **One written OK from Jared** - "we are fine publishing measured latency numbers." One Slack message, keep the reply.

During the project:
6. Review checkpoints - twice: look at the numbers before the first tweet, look at the bot recording before the second. Each is a 15-minute read.
7. Twitter threads - Ivan writes them (his voice), Claude can help draft.

That's all. Everything else Claude Code does.

## How the work will go

Work happens in Claude Code sessions on the server. Rough plan:

- **Week 1:** plumbing. Get both data streams recording to disk, decode the feed format, verify nothing is lost. Boring but critical. (Sessions 1-2)
- **Week 1-2:** the race. Match the same trades across both streams, compute the delay statistics, build the split-screen visual, record it. Internal checkpoint with Jared -> first thread. (Sessions 3-4)
- **Week 2-4:** the bot. Build the order book from the feed, add the external Bitcoin price reference, the simple strategy, demo orders, dashboard. 24-hour test run. Checkpoint -> second thread. (Sessions 5-8)

Calendar time depends on how fast the feed documentation arrives and how many evenings per week - realistically 3-4 weeks part-time to the end of Step B.

## What we get at the end (the artifacts)

1. A public GitHub repo (goes public only after review) with the race tool + the demo bot.
2. A methodology page that survives hostile quants.
3. One latency GIF + one dashboard recording + two tweet threads.
4. A reusable starter kit we can hand to every "what does the feed actually give me?" inbound - which is exactly the gap our research found.

## Safety rails (agreed up front)

- No profit promises anywhere, ever. The bot is openly labeled a dumb example.
- No feed pricing, trial terms, or internal docs in the repo or posts.
- Repo stays private until Ivan + Jared review Step A output.
- Steps A and B involve zero real money.

---
---

# PART 2 - TECHNICAL SPEC (for Claude Code)

You are building this on Ivan's DZ-connected server. Work phase by phase; do not start a phase before the previous one's acceptance criteria pass. After each session, append a short result note (what works, numbers, blockers) to `docs/log.md`.

## Ground rules
1. Honesty is the product: every published number must be reproducible from code in this repo. Methodology documented in `docs/methodology.md`.
2. Same-host comparison only: never compare timestamps across machines. Use one monotonic clock (`CLOCK_MONOTONIC_RAW`) for both sources.
3. Never commit: API keys, wallets, multicast/internal endpoints, any DoubleZero-confidential format details not cleared for publication. `.env` + `.gitignore` from session 1.
4. Repo private until explicitly told otherwise.
5. All order-placing code targets the Kalshi DEMO environment. Production trading endpoints must not appear in Phase 1-2 code paths.

## Phase 0 - Discovery & plumbing

0.1 Environment audit -> `docs/env.md`: server specs/location, `doublezero status` output, feed subscription details ==FILL from Ivan==, feed wire-format doc ==FILL from Ivan==, BTCPERP ticker in feed ==FILL==, Kalshi demo + prod read-only keys present as env vars ==FILL==, NTP sanity.

0.2 Prior art audit: browse github.com/hypnogaba, locate Ivan's Solana trading bot, audit for reuse: lifecycle skeleton (main loop, config, shutdown, reconnects, logging), risk guardrails (position/order-rate limits, kill switch, loss caps), source->event->strategy->execution structure, WS client patterns, monitoring code. Copy code in (no dependency on old repo), strip any keys/endpoints found, record reuse decisions in `docs/env.md`. Solana-specific code (transactions, signing, slots, Jito/shreds) and the sniping strategy logic do not transfer.

0.3 Capture daemons (Python 3.12 + asyncio + uvloop; escalate capture path to Rust only if measured packet loss > 0 at observed rates - decision point end of Phase 0):
- `capture/dz_feed.py`: join feed multicast on the DZ interface; write every packet as `(t_arrival_ns, raw_bytes)` to append-only file.
- `capture/kalshi_ws.py`: Kalshi public WS, subscribe `orderbook_delta` + `trade` for the same market(s); same clock, same storage pattern.
- Acceptance: 30 min simultaneous capture, feed sequence numbers contiguous, WS reconnects (if any) logged.

0.4 Decoder: implement feed message decoder per wire-format doc; unit tests against captured samples. Normalize both sources to:
`Event { source, t_arrival_ns, market, kind: trade|book_delta, price, size, side, seq_or_ids }`

## Phase 1 - Latency Race

1.1 Matching: primary on trades - match (market, price, size, nearest-in-time within window) between feed and WS `trade` channel; verify whether WS trade messages carry an exact id usable for matching (check first capture). Secondary: top-of-book price-change events to the same new value. Per pair: `delta_ms = (t_ws - t_feed)/1e6`, positive = feed first.

1.2 Stats over >= 2h spanning active + quiet periods, >= 500 matched pairs. Report p10/p50/p90/p99, match rate, discards. `race/report.py` renders histogram + timeline PNG.

1.3 `race/live_tui.py`: split-screen TUI - left public WS top-of-book, right feed top-of-book, running delta counter, timestamps. Screenshot/recording friendly.

1.4 `docs/methodology.md`: same host, single location, TCP+TLS WS vs multicast over DZ, time-of-day variance, all caveats explicit.

Acceptance: stats file + PNG + 20-40 s recording + methodology doc. STOP for human review before anything public.

## Phase 2 - Book builder + Paper bot (Kalshi demo env only)

2.1 `book/`: full-depth local book for BTCPERP from feed (snapshot + deltas per format spec; sequence-gap resync). Validation mode: periodic top-of-book cross-check vs WS, divergences logged. Expose async stream of book states.

2.2 Reference: ONE external source - Binance BTCUSDT perp bookTicker WS. Signal v0 (explicitly naive, parameters in one config file): reference mid moves > X bps within T seconds while Kalshi mid lags -> lean direction of move.

2.3 `bot/`: order manager on Kalshi DEMO REST (place/cancel limits, track fills/position). Hard-coded ceilings independent of config: max position, max orders/min, max daily paper loss, kill-switch file checked every loop. Decision log: `(t, book_hash, ref_state, signal, action, result)` - append-only, this log is later content.

2.4 `dash/`: minimal local dashboard (rich TUI or single-page web): book, reference, signal, position, paper PnL. Dark, screenshot-friendly.

Acceptance: 24 h continuous demo run, zero crashes, complete decision log, recorded clip of a volatile window. STOP for human review.

## Phase 3 - deliberately not specced. Do not build.

## Repo layout
```
kalshi-edge-lab/
  SPEC.md  docs/{env,methodology,feed-notes,log}.md
  capture/  race/  book/  bot/  dash/  data/ (gitignored)  scripts/
```
Python 3.12, uv, ruff, pytest. Makefile: `make capture | race | bot-demo`.

## Open questions (resolve with Ivan before session 1)
1. Wire-format doc location; what's publishable.
2. Exact multicast join procedure on this server.
3. Snapshot/recovery mechanism of the feed, or deltas-only?
4. Company constraint on publishing latency numbers - Jared's written OK.
