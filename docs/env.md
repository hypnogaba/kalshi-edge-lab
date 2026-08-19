# Environment audit

## Runtime (local dev machine)
- OS: macOS (darwin). Python: Python 3.12.13. uv: uv 0.11.24 (5e04460c0 2026-06-23 aarch64-apple-darwin).
- Repo: kalshi-edge-lab @ branch phase-0-foundation, HEAD 240ee11.
- Clock: `common/clock.py` uses CLOCK_MONOTONIC_RAW on Linux (the DZ server); falls back to monotonic_ns on macOS dev.

## DZ server (pending — to run ON the server)
- Server specs / location: TODO on DZ server.
- `doublezero status` output: TODO on DZ server.
- NTP sanity: TODO on DZ server.
- The real 30-min prod capture + acceptance (Task 14) runs here, against prod market data.

## Kalshi access
- Demo: key present as env `KALSHI_DEMO_KEY_ID` + private key file (values not recorded). `make check-auth` → HTTP 200 AUTH OK.
- Prod read-only: PENDING (needed for real trades/deltas + latency race). Endpoints in `.env.example`.
- Market: Kalshi BTC = strike-ladder series KXBTCD (daily) / KXBTC, plus KXBTC15M (15-min, most active in prod). Final capture ticker chosen at prod capture time. (Spec's "BTCPERP" does not exist as a single market.)
- Demo has no order flow (all BTC markets volume=0), so demo yields only subscribe acks + empty snapshots — plumbing is validated on demo; real events require prod.

## Reuse decisions (from hypnogaba/tradebot, per SPEC 0.2)
Phase 0 built the core modules clean rather than copying, because tradebot's low-level code is Solana-specific and cleaner to rewrite than to strip. The valuable reuse lands in later phases:
- `execution/paper.py` -> Phase 2 `bot/order_manager.py` (paper order/fill/position tracking maps ~1:1 to Kalshi demo).
- `deploy/*` (systemd, deploy.sh, logrotate) -> running capture daemons on the DZ server.
- Patterns echoed in Phase 0 (lifecycle/reconnect/config/storage) are informed by tradebot's core but written fresh here.
NOT reused (Solana-specific): safety/ (rug/honeypot/helius), tx signing, slots/Jito/shreds, sniping strategy, token scoring.
