# Server deploy guide

## 1. What this is / why a server

This project decodes the DoubleZero (DZ) edge feed of Kalshi crypto perpetuals and measures
how much sooner it delivers each trade than Kalshi's public perps WebSocket. The comparison
only means anything if both feeds are captured on the same machine at the same time — and the
DZ edge feed **only arrives on a Linux host connected to DoubleZero**. A laptop isn't connected
to DZ, so it can't receive that feed.

Development and the offline self-check already work on a laptop. This guide covers the one extra
step: running the real race and the live collectors on a DoubleZero-connected Linux server.

## 2. What you need (once)

- A Linux host (Ubuntu or similar).
- That host connected to DoubleZero. Setup: https://docs.malbeclabs.com/setup
- An access pass for the host's receiving IP. During the beta, DoubleZero grants these — ask
  them if you don't have one yet. Without an access pass, the multicast feed won't reach you
  even if the tunnel is up.
- A Kalshi **PROD** API key that is **read-only** (market data only — no trading permission is
  needed for the race).

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
# 3. Edit .env and set your Kalshi PROD key ID (KALSHI_PROD_KEY_ID=...)
nano .env

# 4. Put the matching private key file here (this exact path/name):
#    secrets/kalshi_prod_key.pem
```

```bash
# 5. Find the Kalshi perps feed's DoubleZero multicast group
doublezero multicast group list
# Look for the Kalshi perps group in the output — that's your GROUP value below.

# 6. Run the race (replace MARKET / GROUP / IFACE with your values)
MARKET=KXBTCPERP GROUP=233.84.178.3 IFACE=doublezero1 bash deploy/run_race.sh
```

- `MARKET` — a Kalshi crypto-perp ticker (e.g. `KXBTCPERP`, `KXETHPERP`).
- `GROUP` — the DZ multicast group address for the Kalshi perps feed, from step 5.
- `IFACE` — the DZ tunnel interface (`doublezero1`); the runner captures via `AF_PACKET`, which
  is required on the tunnel because a normal UDP multicast socket receives nothing there.

```bash
# 7. Read the results
open data/race/race.png     # (or scp it to your laptop and open it there)
# p50 / p90 / p99 latency numbers are also printed to the terminal.
```

## 4. Live web dashboard

A read-only FastAPI + SSE service (`web/server.py`) that serves a self-contained monochrome
page: a live latency scoreboard plus the live decoded feed for every Kalshi crypto perpetual.
It never places orders.

```bash
uv run python -m web.server     # http://localhost:8080 by default
```

The page reads two JSON snapshots written by two collector services that run on the
DZ-connected host:

- `scripts/dz_live_feed.py`    → `data/dz_feed_state.json` (decoded live feed)
- `scripts/dz_latency_race.py` → `data/dz_latency.json` (rolling latency summary)

Both collectors tap the tunnel via `AF_PACKET`, so they need `CAP_NET_RAW` (run under `sudo`
with the venv python); the latency race also needs the Kalshi PROD key in `.env`.

Env knobs for the dashboard (all optional):

- `EDGE_WEB_PORT` — listen port (default `8080`)
- `EDGE_WEB_HOST` — listen host (default `0.0.0.0`)
- `EDGE_WEB_INTERVAL` — refresh interval in seconds (default `2`)

Endpoints: `/` (the page), `/events` (SSE stream), `/api/state` (plain JSON snapshot).

To run it continuously as a service, see `deploy/edge-web.service` (systemd unit template).

Reverse proxy (Caddy, one-liner, TLS handled automatically):

```
edge.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

## 5. Validate with no feed/keys at all

To confirm the code itself is wired correctly (matching, stats, chart rendering) without any DZ
feed or Kalshi credentials:

```bash
uv run python -m scripts.run_race --selfcheck
```

This uses synthetic data and should print `SELFCHECK: PASS`. It's the same check `setup.sh`
runs automatically at the end of setup.

## 6. Free public URL via Cloudflare Tunnel (no domain needed)

Run the dashboard on the DZ server (a host with a normal IP the Kalshi API allows), then expose
it with a tunnel — the server fetches data from its own IP; the tunnel only proxies inbound
HTTP.

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

For an always-on quick tunnel, wrap step (2a) in its own systemd service. One host serves both
the latency race and the public dashboard.
