# Server deploy — plain-language guide

## 1. What this is / why a server

This project measures whether the DoubleZero (DZ) network delivers Kalshi
market data faster than the public internet. The comparison only means
anything if both feeds are captured on the same machine, at the same time —
and the DZ edge feed **only arrives on a Linux host that is connected to
DoubleZero**. A laptop isn't connected to DZ, so it can't receive that feed.

Development and the offline self-check already work fine on a laptop. This
guide is for the one extra step: running the real race (and optionally the
demo bot) on a Linux server that has a DoubleZero connection.

## 2. What you need (once)

- A Linux host (Ubuntu or similar).
- That host connected to DoubleZero. Setup instructions:
  https://docs.malbeclabs.com/setup
- An access pass for the host's receiving IP. During the beta, DoubleZero
  grants these — ask them if you don't have one yet. Without an access pass,
  the multicast feed won't reach you even if the tunnel is up.
- A Kalshi **PROD** API key that is **read-only** (market data only — no
  trading permission needed for the race itself).

## 3. Steps

```bash
# 1. Get the code onto the server
git clone <your-repo-url> kalshi-edge-lab
cd kalshi-edge-lab

# 2. One-time setup (installs uv, deps, creates .env/data/secrets, runs a smoke test)
bash deploy/setup.sh
```

`setup.sh` will tell you if `.env` was just created from `.env.example`. If so:

```bash
# 3. Edit .env and set your Kalshi PROD key ID
#    (KALSHI_PROD_KEY_ID=...)
nano .env

# 4. Put the matching private key file here (this exact path/name):
#    secrets/kalshi_prod_key.pem
```

```bash
# 5. Find the Kalshi feed's DoubleZero multicast group
doublezero multicast group list
# Look for the Kalshi group in the output — that's your GROUP value below.

# 6. Run the race (replace MARKET / GROUP / IFACE with your values)
MARKET=KXBTC-25DEC31 GROUP=239.1.1.1 IFACE=eth0 bash deploy/run_race.sh
```

- `MARKET` — a concrete active Kalshi ticker (e.g. a BTC strike-ladder
  market). Kalshi has no single "BTCPERP" market — pick one that's live.
- `GROUP` — the DZ multicast group address for the Kalshi feed, from step 5.
- `IFACE` — the network interface used to join the multicast group (usually
  the DZ tunnel interface, `doublezero1`, or the physical NIC your routing
  table uses for that multicast route — check with your DZ setup docs if
  unsure).

```bash
# 7. Read the results
open data/race/race.png     # (or scp it to your laptop and open it there)
# p50 / p90 / p99 latency numbers are also printed to the terminal.
```

## 4. Optional — run the demo bot as a service

If you also want the demo trading bot (`bot/run.py`) running continuously
under systemd (auto-restart on crash, starts on boot):

```bash
# Fill in <USER> and <REPO_PATH> and install the unit:
sed -e "s|<USER>|$(whoami)|g" -e "s|<REPO_PATH>|$(pwd)|g" \
    deploy/kalshi-edge-bot.service | sudo tee /etc/systemd/system/kalshi-edge-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now kalshi-edge-bot

# Check on it:
sudo systemctl status kalshi-edge-bot
journalctl -u kalshi-edge-bot -f

# Emergency stop (kill switch, without touching the service):
touch data/KILL
```

See `deploy/kalshi-edge-bot.service` for the full unit file and comments.

## 5. Live web dashboard

A small FastAPI service that reuses the same Kalshi/Binance/bot-signal modules as
`bot/run.py` and streams the live state to a browser over Server-Sent Events. Read-only
— it never places orders.

```bash
uv run python -m web.server     # http://localhost:8080 by default
```

Env knobs (all optional):

- `EDGE_WEB_PORT` — listen port (default `8080`)
- `EDGE_WEB_HOST` — listen host (default `0.0.0.0`)
- `EDGE_WEB_INTERVAL` — refresh interval in seconds (default `3`)
- `EDGE_WEB_NEAR` — number of near-money markets to watch (default `8`)

Endpoints: `/` (the page), `/events` (SSE stream), `/api/state` (plain JSON snapshot).
If `data/race/race_stats.json` exists (written by `scripts/run_race.py`), its stats are
shown on the page and the "DZ feed" pill flips from `pending` to `live`.

To run it continuously as a service, see `deploy/edge-web.service` (systemd unit
template, same install pattern as `deploy/kalshi-edge-bot.service` above).

Reverse proxy (Caddy, one-liner, TLS handled automatically):

```
edge.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

## 6. Validate with no feed/keys at all

If you just want to confirm the code itself is wired correctly (matching,
stats, chart rendering) without any DZ feed or Kalshi credentials:

```bash
uv run python -m scripts.run_race --selfcheck
```

This uses synthetic data and should print `SELFCHECK: PASS`. It's the same
check `deploy/setup.sh` runs automatically at the end of setup.

## 7. Free public URL via Cloudflare Tunnel (no domain needed)

Do NOT try to host the dashboard on free serverless (Vercel / Cloudflare
Pages / GitHub Pages). Kalshi and Binance **rate-limit or block shared cloud
egress IPs** (observed: Kalshi `429`, Binance `403` from Cloudflare). The
dashboard must run on a host with a normal IP that those APIs allow — your DZ
server or any VPS/box — and be exposed with a tunnel. The server fetches the
data from its own (allowed) IP; the tunnel only proxies inbound HTTP.

Run the dashboard, then tunnel to it:

```bash
# 1. run the dashboard on the host (default :8080), e.g. via systemd:
sudo cp deploy/edge-web.service /etc/systemd/system/  # edit <USER>/<REPO_PATH> first
sudo systemctl enable --now edge-web

# 2. install cloudflared, then either:

# (a) quick tunnel — instant, free, no domain, RANDOM url that changes on restart:
cloudflared tunnel --url http://localhost:8080
#   → prints https://<random>.trycloudflare.com

# (b) named tunnel — stable url on a domain you already have on Cloudflare:
cloudflared tunnel login
cloudflared tunnel create edge-lab
cloudflared tunnel route dns edge-lab edge.<your-domain>
cloudflared tunnel run --url http://localhost:8080 edge-lab
#   → stable https://edge.<your-domain>
```

For an always-on quick tunnel, wrap step (2a) in its own systemd service.
This is the recommended home for the live dashboard once the DZ server is up —
one host serves both the latency race and the public dashboard.
