# Runbook — running the Kalshi × DoubleZero latency race on the server

The race compares two ways of getting the **same Kalshi crypto-perp trades** on **one host**:

- **Public baseline** — Kalshi's public perps WebSocket (`external-api-margin-ws.kalshi.com`).
- **Edge path** — the DoubleZero edge multicast feed carrying Kalshi perps.

It reports `t_dz − t_public` per matched trade. **Negative = DoubleZero delivered it first.**

The code is complete; this runbook is the server-side operation.

## Prerequisites (operator)

1. **Linux host on DoubleZero.** The `doublezero` client installed and the tunnel up:
   ```bash
   ip a s doublezero1        # should show the GRE tunnel interface
   ```
   GRE (IP protocol 47) allowed inbound; on AWS disable the ENI source/dest check.
2. **Access pass** granted for the receiving IP (DoubleZero grants this during beta).
3. **Kalshi prod read-only key** for the public baseline (Kalshi authenticates the socket at connect):
   - Create at kalshi.com → `/account/profile` → API Keys.
   - Put the private key at `secrets/kalshi_prod_key.pem` and set in `.env`:
     ```
     KALSHI_PROD_KEY_ID=<key id>
     KALSHI_PROD_PRIVATE_KEY_PATH=secrets/kalshi_prod_key.pem
     ```

## Step 1 — find the Kalshi feed's multicast group

```bash
doublezero multicast group list
```
Note the **multicast address** and the **mktdata + refdata ports** for the Kalshi perps feed. You supply these to the runner below.

## Step 2 — pick the Kalshi perp(s)

The public WS baseline needs Kalshi perp tickers to subscribe to (e.g. `KXBTCPERP`, `KXETHPERP`).

## Step 3 — run the race

```bash
uv run python -m scripts.run_race \
  --minutes 10 \
  --market <KALSHI_TICKER> \
  --group <MULTICAST_ADDR> --mktdata-port <P1> --refdata-port <P2> \
  --link doublezero1 \
  --out-dir data/race
```

The runner captures both feeds simultaneously on this host, then prints:
```
matched N trades  (match rate ...%)
p10 / p50 / p90 / p99 = ... ms     (negative = DoubleZero faster)
report: data/race/race.png
```
and writes the histogram + timeline PNG plus `data/race/race_stats.json`.

`--link doublezero1` captures via `AF_PACKET`, which is required on the DZ tunnel (a normal UDP multicast socket receives nothing there). `deploy/run_race.sh` wraps this with tunnel and config checks.

## Live collectors (for the dashboard)

Two long-running services feed the live web dashboard:

```bash
sudo .venv/bin/python -m scripts.dz_live_feed    --link doublezero1 --group <ADDR> ...
sudo .venv/bin/python -m scripts.dz_latency_race --ticker KXBTCPERP
```

They write `data/dz_feed_state.json` and `data/dz_latency.json`, which `web/server.py` reads and serves. Both need `CAP_NET_RAW` for `AF_PACKET`; the latency race also needs the Kalshi PROD key in `.env`.

## Validate the tooling without any feed/key

```bash
uv run python -m scripts.run_race --selfcheck
```
Builds a synthetic stream + a +3 ms delayed copy and confirms the matcher/stats recover exactly +3.000 ms (100% match). Proves the compute path independent of live data.

## Notes

- Never commit `.env`, `secrets/`, or `data/` (all gitignored).
- Publish latency numbers only from data reproducible by this repo (see `docs/methodology.md`).
