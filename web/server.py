"""Live web dashboard service: FastAPI app that refreshes real Kalshi + Binance +
bot-signal data in the background and serves it to a browser over SSE (and a plain
JSON endpoint), plus a self-contained monochrome HTML page.

Reuses the same building blocks as bot/run.py — no re-implementation of Kalshi
selection, spot-fetch, or signal logic:
  - sources.kalshi_rest.client.KalshiRestClient  (markets/trades)
  - sources.kalshi_rest.selector.{parse_strike,nearest_markets}
  - bot.run.{is_threshold_ticker,fetch_one_shot_spot}
  - bot.signal.{decide,SignalConfig,Decision}
  - bot.config.BotConfig (default tuning)

DEMO/read-only: this service never places orders.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from bot.config import BotConfig
from bot.run import fetch_one_shot_spot, is_threshold_ticker
from bot.signal import Decision, SignalConfig, decide
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets, parse_strike

REFRESH_SECONDS = float(os.environ.get("EDGE_WEB_INTERVAL", "3"))
NEAR = int(os.environ.get("EDGE_WEB_NEAR", "8"))
RACE_STATS_PATH = Path("data/race/race_stats.json")
_SERIES = ("KXBTC", "KXBTCD")

# Module-level live state, served as-is by /api/state and /events.
STATE: dict = {
    "spot": None,
    "updated_ns": None,
    "updated_iso": None,
    "markets": [],
    "dz_feed": "pending",
    "race": None,
}

_watchlist: list[str] | None = None  # built once, cached (see _ensure_watchlist)
_refresh_task: asyncio.Task | None = None


def _signal_config() -> SignalConfig:
    cfg = BotConfig.from_env()
    return SignalConfig(cfg.entry_dollars, cfg.max_yes_cents, cfg.min_yes_cents)


async def _ensure_watchlist(client: KalshiRestClient, spot: float | None) -> list[str]:
    """Build the near-money threshold-market watchlist once (merging KXBTC + KXBTCD)
    and cache it. Only caches a non-empty result so a transient failure on the very
    first refresh doesn't wedge the dashboard empty forever."""
    global _watchlist
    if _watchlist is not None:
        return _watchlist
    if spot is None:
        return []

    tickers: list[str] = []
    for series in _SERIES:
        try:
            markets = await asyncio.to_thread(client.markets, series)
        except Exception:  # noqa: BLE001, S112 - one bad series must not break selection
            continue
        tickers.extend(m["ticker"] for m in markets if m.get("ticker"))

    threshold_tickers = [t for t in tickers if is_threshold_ticker(t) and parse_strike(t) is not None]
    if not threshold_tickers:
        return []

    built = nearest_markets(threshold_tickers, spot=spot, n=NEAR)
    if built:
        _watchlist = built
    return built


async def refresh_once(client: KalshiRestClient, sig_cfg: SignalConfig) -> None:
    """One refresh cycle: Binance spot, per-market Kalshi trade -> signal, race stats."""
    try:
        spot = await asyncio.to_thread(fetch_one_shot_spot)
    except Exception:  # noqa: BLE001 - keep last-known spot on failure
        spot = None
    if spot is not None:
        STATE["spot"] = spot

    watchlist = await _ensure_watchlist(client, STATE["spot"])

    markets_out = []
    for ticker in watchlist:
        strike = parse_strike(ticker)
        yes_cents = None
        try:
            trades = await asyncio.to_thread(client.trades, ticker, 1)
            if trades:
                yes_cents = round(float(trades[0]["yes_price_dollars"]) * 100)
        except Exception:  # noqa: BLE001 - one bad market must not break the refresh
            yes_cents = None

        signal_val = Decision.HOLD.value
        if strike is not None and STATE["spot"] is not None and yes_cents is not None:
            try:
                signal_val = decide(strike, True, yes_cents, STATE["spot"], sig_cfg).value
            except Exception:  # noqa: BLE001 - fall back to HOLD
                signal_val = Decision.HOLD.value

        markets_out.append(
            {"ticker": ticker, "strike": strike, "yes_cents": yes_cents, "signal": signal_val}
        )
    STATE["markets"] = markets_out

    if RACE_STATS_PATH.exists():
        try:
            STATE["race"] = json.loads(RACE_STATS_PATH.read_text())
            STATE["dz_feed"] = "live"
        except Exception:  # noqa: BLE001 - malformed file, treat as not-live
            STATE["race"] = None
            STATE["dz_feed"] = "pending"
    else:
        STATE["race"] = None
        STATE["dz_feed"] = "pending"

    STATE["updated_ns"] = time.monotonic_ns()
    STATE["updated_iso"] = datetime.now(UTC).isoformat()


async def _refresh_loop(client: KalshiRestClient) -> None:
    sig_cfg = _signal_config()
    while True:
        try:
            await refresh_once(client, sig_cfg)
        except Exception:  # noqa: BLE001, S110 - background loop must never die
            pass
        await asyncio.sleep(REFRESH_SECONDS)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _refresh_task
    client = KalshiRestClient()
    _refresh_task = asyncio.create_task(_refresh_loop(client))
    try:
        yield
    finally:
        _refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _refresh_task
        client.close()


app = FastAPI(lifespan=_lifespan)


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse(STATE)


@app.get("/events")
async def events(request: Request) -> StreamingResponse:
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(STATE)}\n\n"
            await asyncio.sleep(REFRESH_SECONDS)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_PAGE_HTML)


_PAGE_HTML = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Edge Latency Lab — live</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root{
    --ink:#FFFFFF; --panel:#FFFFFF; --panel-2:#F2F3F5; --line:rgba(0,0,0,.13);
    --fg:#0A0A0B; --muted:#585A61; --faint:#8A8D95;
    --shadow:0 1px 0 rgba(0,0,0,.03), 0 10px 30px -22px rgba(0,0,0,.4);
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --ink:#09090A; --panel:#141416; --panel-2:#1B1C1F; --line:rgba(255,255,255,.14);
      --fg:#ECEDEF; --muted:#A0A2A9; --faint:#6C6E76;
      --shadow:0 1px 0 rgba(0,0,0,.5), 0 18px 44px -26px rgba(0,0,0,.9);
    }
  }
  :root[data-theme="dark"]{
    --ink:#09090A; --panel:#141416; --panel-2:#1B1C1F; --line:rgba(255,255,255,.14);
    --fg:#ECEDEF; --muted:#A0A2A9; --faint:#6C6E76;
    --shadow:0 1px 0 rgba(0,0,0,.5), 0 18px 44px -26px rgba(0,0,0,.9);
  }
  :root[data-theme="light"]{
    --ink:#FFFFFF; --panel:#FFFFFF; --panel-2:#F2F3F5; --line:rgba(0,0,0,.13);
    --fg:#0A0A0B; --muted:#585A61; --faint:#8A8D95;
    --shadow:0 1px 0 rgba(0,0,0,.03), 0 10px 30px -22px rgba(0,0,0,.4);
  }
  *{box-sizing:border-box}
  @media (prefers-reduced-motion: reduce){ *{transition:none!important; animation:none!important} }
  html{-webkit-text-size-adjust:100%}
  body{margin:0; background:var(--ink); color:var(--fg);
    font-family:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased}
  .wrap{max-width:960px; margin:0 auto; padding:0 24px}
  a{color:var(--fg); text-decoration:underline; text-underline-offset:2px; text-decoration-color:var(--faint)}
  a:hover{text-decoration-color:var(--fg)}
  h1{font-family:"Archivo",system-ui,sans-serif; font-weight:800; letter-spacing:-.01em; margin:0}
  .mono{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums}
  header.bar{position:sticky; top:0; z-index:20; backdrop-filter:blur(10px);
    background:color-mix(in srgb, var(--ink) 88%, transparent); border-bottom:1px solid var(--line)}
  .bar-in{display:flex; align-items:center; gap:14px; height:64px; flex-wrap:wrap}
  .bar-in h1{font-size:18px}
  .spacer{flex:1}
  .pill{font-family:"IBM Plex Mono"; font-size:11px; letter-spacing:.04em; text-transform:uppercase;
    padding:4px 10px; border-radius:999px; border:1px solid var(--line); color:var(--muted); white-space:nowrap}
  .pill.live{border-color:var(--fg); color:var(--fg)}
  .pill.pending{color:var(--faint); border-style:dashed}
  .updated{font-family:"IBM Plex Mono"; font-size:12px; color:var(--faint); white-space:nowrap}
  main{padding:32px 0 20px}
  .spotline{font-family:"IBM Plex Mono"; font-size:13px; color:var(--muted); margin:0 0 18px}
  .spotline b{color:var(--fg); font-weight:600; font-size:15px}
  .card{background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); overflow:hidden}
  table.tbl{width:100%; border-collapse:collapse; font-family:"IBM Plex Mono"; font-size:13px}
  .tbl th,.tbl td{text-align:left; padding:10px 14px; border-bottom:1px solid var(--line)}
  .tbl th{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint); font-weight:500}
  .tbl td.num{text-align:right; font-variant-numeric:tabular-nums}
  .tbl tr:last-child td{border-bottom:0}
  .chip{font-family:"IBM Plex Mono"; font-size:10.5px; letter-spacing:.04em; text-transform:uppercase;
    padding:2px 8px; border-radius:5px; border:1px solid var(--fg); white-space:nowrap; display:inline-block}
  .chip.yes{background:var(--fg); color:var(--ink)}
  .chip.no{background:transparent; color:var(--fg)}
  .chip.hold{background:transparent; color:var(--faint); border-color:var(--line); border-style:dashed}
  .empty{padding:22px 14px; color:var(--faint); font-family:"IBM Plex Mono"; font-size:13px}
  #race-line{margin:14px 2px 0; font-family:"IBM Plex Mono"; font-size:12.5px; color:var(--muted)}
  footer{border-top:1px solid var(--line); margin-top:28px; padding:22px 0 40px;
    color:var(--muted); font-family:"IBM Plex Mono"; font-size:12.5px}
  :focus-visible{outline:2px solid var(--fg); outline-offset:2px; border-radius:6px}
</style>

<header class="bar">
  <div class="wrap bar-in">
    <h1>Edge Latency Lab — live</h1>
    <span class="pill pending" id="dzpill">DZ feed: pending</span>
    <span class="spacer"></span>
    <span class="updated mono" id="updated">updated —</span>
  </div>
</header>

<main class="wrap">
  <p class="spotline">BTC spot <b id="spot">—</b></p>
  <div class="card">
    <table class="tbl">
      <thead>
        <tr>
          <th>Market (BTC &ge; strike?)</th>
          <th class="num">Strike</th>
          <th class="num">Yes&cent;</th>
          <th class="num">Spot&minus;Strike</th>
          <th>Signal</th>
        </tr>
      </thead>
      <tbody id="mkt-body">
        <tr><td colspan="5" class="empty">waiting for first refresh…</td></tr>
      </tbody>
    </table>
  </div>
  <p id="race-line" style="display:none"></p>
</main>

<footer>
  <div class="wrap">
    <a href="https://github.com/hypnogaba/kalshi-edge-lab">github.com/hypnogaba/kalshi-edge-lab</a>
    <p style="margin:10px 0 0; font-size:11.5px; color:var(--faint)">Independent project. Not affiliated with, endorsed by, or an official product of DoubleZero or Kalshi — those names refer only to the systems being measured.</p>
  </div>
</footer>

<script>
(function(){
  var lastState = null;

  function fmtMoney(n){
    if(n == null) return '—';
    return '$' + Number(n).toLocaleString(undefined,{minimumFractionDigits:2, maximumFractionDigits:2});
  }

  function renderUpdated(){
    var el = document.getElementById('updated');
    if(!lastState || !lastState.updated_iso){ el.textContent = 'updated —'; return; }
    var secs = Math.max(0, Math.round((Date.now() - new Date(lastState.updated_iso).getTime())/1000));
    el.textContent = 'updated ' + secs + 's ago';
  }

  function render(state){
    lastState = state;
    document.getElementById('spot').textContent = fmtMoney(state.spot);

    var pill = document.getElementById('dzpill');
    var live = state.dz_feed === 'live';
    pill.textContent = 'DZ feed: ' + (state.dz_feed || 'pending');
    pill.className = 'pill ' + (live ? 'live' : 'pending');

    var tbody = document.getElementById('mkt-body');
    var markets = state.markets || [];
    if(!markets.length){
      tbody.innerHTML = '<tr><td colspan="5" class="empty">no markets yet…</td></tr>';
    } else {
      tbody.innerHTML = markets.map(function(m){
        var strike = m.strike != null ? Number(m.strike).toLocaleString(undefined,{maximumFractionDigits:2}) : '—';
        var yesCents = m.yes_cents != null ? m.yes_cents + '¢' : '—';
        var diff = (state.spot != null && m.strike != null) ? (state.spot - m.strike) : null;
        var diffTxt = diff != null ? (diff >= 0 ? '+' : '') + diff.toFixed(2) : '—';
        var sigTxt = 'HOLD', sigClass = 'chip hold';
        if(m.signal === 'buy_yes'){ sigTxt = 'BUY YES'; sigClass = 'chip yes'; }
        else if(m.signal === 'buy_no'){ sigTxt = 'BUY NO'; sigClass = 'chip no'; }
        return '<tr><td>' + m.ticker + '</td>' +
          '<td class="num">' + strike + '</td>' +
          '<td class="num">' + yesCents + '</td>' +
          '<td class="num">' + diffTxt + '</td>' +
          '<td><span class="' + sigClass + '">' + sigTxt + '</span></td></tr>';
      }).join('');
    }

    var raceEl = document.getElementById('race-line');
    if(state.race && state.race.stats && state.race.stats.n){
      var s = state.race.stats;
      raceEl.style.display = '';
      raceEl.textContent = 'race latency — p50 ' + s.p50_ms + 'ms · p90 ' + s.p90_ms + 'ms · p99 ' + s.p99_ms + 'ms (n=' + s.n + ')';
    } else {
      raceEl.style.display = 'none';
    }

    renderUpdated();
  }

  function poll(){
    fetch('/api/state').then(function(r){ return r.json(); }).then(render).catch(function(){});
  }

  poll();
  setInterval(renderUpdated, 1000);

  if(typeof EventSource !== 'undefined'){
    var es = new EventSource('/events');
    es.onmessage = function(ev){
      try { render(JSON.parse(ev.data)); } catch(e) {}
    };
    es.onerror = function(){
      es.close();
      setInterval(poll, 3000);
    };
  } else {
    setInterval(poll, 3000);
  }
})();
</script>
</html>
"""


def main() -> None:
    import uvicorn

    host = os.environ.get("EDGE_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("EDGE_WEB_PORT", "8080"))
    uvicorn.run("web.server:app", host=host, port=port)


if __name__ == "__main__":
    main()
