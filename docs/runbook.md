# Runbook — running the Kalshi × DoubleZero latency race on the server

The race compares two ways of getting the **same Kalshi market data** on **one host**:

- **Direct baseline** — the public Kalshi WebSocket.
- **Fast path** — the DoubleZero edge multicast feed carrying Kalshi.

It reports `t_dz − t_public` per matched trade. **Negative = DoubleZero delivered it first.**

Everything is built. This runbook is the server-side operation.

## Prerequisites (operator)

1. **Linux host on DoubleZero.** The `doublezero` client installed and the tunnel up:
   ```bash
   ip a s doublezero1        # should show the GRE tunnel interface
   ```
   GRE (IP protocol 47) allowed inbound; on AWS disable the ENI source/dest check.
2. **Access pass** granted for the receiving IP (DoubleZero grants this during beta).
3. **Kalshi prod read-only key** for the direct baseline (Kalshi signs even public channels):
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
Note the **group code / multicast address** and the **mktdata + refdata ports** for the Kalshi feed (the same way `tiredsolid → 233.84.178.15` identified the Hyperliquid example feed in the reference). You supply these to the runner below.

## Step 2 — pick the Kalshi market(s)

The public WS baseline needs Kalshi tickers to subscribe to. Find active BTC markets:
```bash
uv run python -m scripts.discover_markets --env prod
```
Pick an active ticker (e.g. an hourly `KXBTC-*`).

## Step 3 — run the race

```bash
uv run python -m scripts.run_race \
  --minutes 10 \
  --market <KALSHI_TICKER> \
  --group <MULTICAST_ADDR> --mktdata-port <P1> --refdata-port <P2> \
  --iface <RECEIVING_IP> \
  --out-dir data/race
```

The runner captures both feeds simultaneously on this host, then prints:
```
matched N trades  (match rate ...%)
p10 / p50 / p90 / p99 = ... ms     (negative = DoubleZero faster)
report: data/race/race.png
```
and writes the histogram + timeline PNG.

## Step 4 — the split-screen view (for recording)

```bash
uv run python -m race.live_tui     # left: public Kalshi WS BBO, right: DZ feed BBO, running delta
```

## Validate the tooling without any feed/key

```bash
uv run python -m scripts.run_race --selfcheck
```
Builds a synthetic stream + a +3 ms delayed copy and confirms the matcher/stats recover exactly +3.000 ms (100% match). Proves the compute path independent of live data.

## Safety

- All order-placing code (the demo bot) targets the Kalshi **demo** environment only; the race places nothing.
- Never commit `.env`, `secrets/`, or `data/` (all gitignored).
- Publish latency numbers only from data reproducible by this repo (see `docs/methodology.md` once written).
