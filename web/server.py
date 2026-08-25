"""Public dashboard for the DoubleZero Kalshi crypto-perps edge feed.

A read-only FastAPI app that serves a self-contained monochrome page showing,
live: (1) a latency benchmark of the DoubleZero edge feed vs Kalshi's public
perps WebSocket, and (2) the live decoded feed for every Kalshi crypto
perpetual. It only reads two JSON snapshots written by the two collector
services and never places orders or touches funds:
  - data/dz_latency.json     (scripts.dz_latency_race)
  - data/dz_feed_state.json  (scripts.dz_live_feed)
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

REFRESH_SECONDS = float(os.environ.get("EDGE_WEB_INTERVAL", "2"))
DZ_FEED_STATE_PATH = Path("data/dz_feed_state.json")
DZ_LATENCY_PATH = Path("data/dz_latency.json")
DZ_FRESH_SECONDS = 15  # a snapshot older than this is treated as not-live

STATE: dict = {
    "updated_ns": None,
    "updated_iso": None,
    "dz_feed": "pending",
    "dz_live": None,
    "latency": None,
}

_refresh_task: asyncio.Task | None = None


def _read_fresh(path: Path) -> dict | None:
    """Load a collector JSON snapshot, or None if missing/stale/malformed."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - malformed => treat as absent
        return None
    if time.time() - float(data.get("updated_at", 0)) >= DZ_FRESH_SECONDS:
        return None
    return data


async def refresh_once() -> None:
    live = _read_fresh(DZ_FEED_STATE_PATH)
    STATE["dz_live"] = live
    STATE["dz_feed"] = "live" if live else "pending"
    STATE["latency"] = _read_fresh(DZ_LATENCY_PATH)
    STATE["updated_ns"] = time.monotonic_ns()
    STATE["updated_iso"] = datetime.now(UTC).isoformat()


async def _refresh_loop() -> None:
    while True:
        try:
            await refresh_once()
        except Exception:  # noqa: BLE001, S110 - background loop must never die
            pass
        await asyncio.sleep(REFRESH_SECONDS)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _refresh_task
    _refresh_task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        _refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _refresh_task


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
<title>Kalshi Perps over DoubleZero</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root{
    --ink:#FFFFFF; --panel:#FFFFFF; --panel-2:#F2F3F5; --line:rgba(0,0,0,.13);
    --fg:#0A0A0B; --muted:#585A61; --faint:#8A8D95; --accent:#12B07E;
    --shadow:0 1px 0 rgba(0,0,0,.03), 0 10px 30px -22px rgba(0,0,0,.4);
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --ink:#09090A; --panel:#141416; --panel-2:#1B1C1F; --line:rgba(255,255,255,.14);
      --fg:#ECEDEF; --muted:#A0A2A9; --faint:#6C6E76; --accent:#3AD699;
      --shadow:0 1px 0 rgba(0,0,0,.5), 0 18px 44px -26px rgba(0,0,0,.9);
    }
  }
  :root[data-theme="dark"]{
    --ink:#09090A; --panel:#141416; --panel-2:#1B1C1F; --line:rgba(255,255,255,.14);
    --fg:#ECEDEF; --muted:#A0A2A9; --faint:#6C6E76; --accent:#3AD699;
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
  h1{font-family:"Archivo",system-ui,sans-serif; font-weight:800; letter-spacing:-.01em; margin:0}
  a{color:var(--fg); text-decoration:underline; text-underline-offset:2px; text-decoration-color:var(--faint)}
  a:hover{text-decoration-color:var(--fg)}
  .winstrip{display:flex; gap:2px; align-items:flex-end; height:34px; margin:2px 0 2px}
  .ws-cell{flex:1 1 0; min-width:2px; height:100%; background:var(--line); border-radius:1px}
  .ws-cell.win{background:var(--accent)}
  .ws-legend{display:flex; gap:16px; margin:8px 0 0; font-family:"IBM Plex Mono"; font-size:11px; color:var(--faint)}
  .ws-dot{display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:6px; vertical-align:middle}
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
  main{padding:30px 0 20px}
  .card{background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); overflow:hidden}
  table.tbl{width:100%; border-collapse:collapse; font-family:"IBM Plex Mono"; font-size:13px}
  .tbl th,.tbl td{text-align:left; padding:10px 14px; border-bottom:1px solid var(--line)}
  .tbl th{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint); font-weight:500}
  .tbl th.num,.tbl td.num{text-align:right; font-variant-numeric:tabular-nums}
  .tbl tr:last-child td{border-bottom:0}
  .empty{padding:22px 14px; color:var(--faint); font-family:"IBM Plex Mono"; font-size:13px}

  .panel{margin:24px 0 34px}
  .phead{display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:8px}
  .panel h2{font-family:"Archivo",system-ui,sans-serif; font-weight:800; letter-spacing:-.01em; font-size:21px; margin:0}
  .explainer{font-family:"IBM Plex Mono"; font-size:12.5px; color:var(--muted); margin:0 0 20px; max-width:640px}
  .subnote{margin:10px 0 0; font-family:"IBM Plex Mono"; font-size:12px; color:var(--faint)}
  .statrow{margin:6px 0 0; font-family:"IBM Plex Mono"; font-size:12px; color:var(--muted)}
  .meta{margin:12px 2px 0; font-family:"IBM Plex Mono"; font-size:12px; color:var(--faint)}

  .scoreboard{display:grid; grid-template-columns:auto 1fr; gap:28px; align-items:center;
    background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); padding:22px 24px}
  @media (max-width:640px){ .scoreboard{grid-template-columns:1fr; justify-items:center; text-align:center} }
  .gauge-wrap{display:flex; flex-direction:column; align-items:center; gap:10px}
  .gauge{--pct:0; width:128px; height:128px; border-radius:50%;
    background:conic-gradient(var(--fg) calc(var(--pct)*1%), var(--line) 0);
    display:flex; align-items:center; justify-content:center}
  .gauge-hole{width:98px; height:98px; border-radius:50%; background:var(--panel);
    display:flex; flex-direction:column; align-items:center; justify-content:center}
  .gauge-num{font-family:"Archivo",system-ui,sans-serif; font-weight:800; font-size:26px; letter-spacing:-.01em}
  .gauge-unit{font-family:"IBM Plex Mono"; font-size:9.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--faint); margin-top:2px}
  .gauge-label{margin:0; font-family:"IBM Plex Mono"; font-size:11px; color:var(--faint); max-width:150px; text-align:center}
  .compare-title{margin:0 0 10px; font-size:14px; font-weight:600}
  .compare-row{display:flex; align-items:baseline; gap:10px; padding:6px 0; border-bottom:1px solid var(--line)}
  .compare-row:last-of-type{border-bottom:0}
  .compare-k{font-family:"IBM Plex Mono"; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint); width:32px}
  .compare-v{font-size:15px; font-weight:600}

  .stats{display:grid; grid-template-columns:repeat(4,1fr); gap:16px;
    background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); padding:20px 22px}
  @media (max-width:640px){ .stats{grid-template-columns:1fr 1fr} }
  .stat{display:flex; flex-direction:column; gap:4px}
  .stat-k{font-family:"IBM Plex Mono"; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--faint)}
  .stat-v{font-family:"IBM Plex Mono"; font-size:18px; font-weight:600; font-variant-numeric:tabular-nums}

  .facts{display:grid; grid-template-columns:1fr 1fr; gap:14px 28px;
    background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); padding:22px 24px}
  @media (max-width:640px){ .facts{grid-template-columns:1fr} }
  .fact-k{font-family:"IBM Plex Mono"; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--faint); margin-bottom:2px}
  .fact-v{font-size:14px}
  footer{border-top:1px solid var(--line); margin-top:28px; padding:20px 0 40px; color:var(--faint); font-family:"IBM Plex Mono"; font-size:12px}
  :focus-visible{outline:2px solid var(--fg); outline-offset:2px; border-radius:6px}
</style>

<header class="bar">
  <div class="wrap bar-in">
    <h1>Kalshi Perps &middot; DoubleZero</h1>
    <span class="pill pending" id="dzpill">feed: pending</span>
    <span class="spacer"></span>
    <span class="updated mono" id="updated">updated &mdash;</span>
  </div>
</header>

<main class="wrap">
  <section class="panel" aria-labelledby="score-title">
    <div class="phead">
      <h2 id="score-title">How much sooner you get the data</h2>
    </div>
    <p class="explainer">Two ways to get the <b>same Kalshi trade</b> to your server, side by side: the <a href="https://doublezero.xyz/edge/subscribe"><b>DoubleZero edge feed</b></a> vs <b>Kalshi&rsquo;s own public API</b> &mdash; the perpetuals WebSocket (<span class="mono">external-api-margin-ws.kalshi.com</span>) that anyone can connect to directly. Both are received on one machine and timed on one clock, and each trade is matched across the two by exchange timestamp, price and size &mdash; so there is no cross-machine clock skew. Below: how often, and by how much, the DoubleZero copy of a trade arrives first.</p>
    <div class="scoreboard">
      <div class="gauge-wrap">
        <div class="gauge" id="score-gauge">
          <div class="gauge-hole">
            <div class="gauge-num mono" id="score-winrate">&mdash;</div>
            <div class="gauge-unit">arrives first</div>
          </div>
        </div>
        <p class="gauge-label">of trades reach you first over DoubleZero</p>
      </div>
      <div class="compare">
        <h3 class="compare-title">Typical lead over the public feed</h3>
        <div class="compare-row"><span class="compare-k" style="width:auto; letter-spacing:.02em">Median</span><span class="compare-v mono" id="score-p50" style="font-size:22px">&mdash; ms</span></div>
        <p class="statrow mono" id="score-statrow">matched &mdash; trades &middot; rolling window</p>
        <p class="subnote" id="score-note">Live, rolling window &mdash; one host, one monotonic clock, no cross-machine skew.</p>
      </div>
    </div>
    <div id="winstrip-wrap" style="margin-top:16px; display:none">
      <div class="winstrip" id="winstrip"></div>
      <div class="ws-legend">
        <span><span class="ws-dot" style="background:var(--accent)"></span>DoubleZero first</span>
        <span><span class="ws-dot" style="background:var(--line)"></span>public first</span>
        <span id="ws-count"></span>
      </div>
    </div>
  </section>

  <section class="panel" aria-labelledby="feed-title">
    <div class="phead">
      <h2 id="feed-title">The feed, live right now</h2>
    </div>
    <p class="explainer">Every Kalshi crypto perpetual &mdash; full top-of-book &amp; trades &mdash; streaming over the DoubleZero edge network and decoded here in real time. Live throughput below.</p>
    <div class="stats" id="feed-stats" style="display:none">
      <div class="stat"><span class="stat-k">Markets live</span><span class="stat-v mono" id="feed-mkts">&mdash;</span></div>
      <div class="stat"><span class="stat-k">Trades / s</span><span class="stat-v mono" id="feed-tps">&mdash;</span></div>
      <div class="stat"><span class="stat-k">Msgs / s</span><span class="stat-v mono" id="feed-mps">&mdash;</span></div>
      <div class="stat"><span class="stat-k">Feed uptime</span><span class="stat-v mono" id="feed-uptime">&mdash;</span></div>
    </div>
    <div class="card" style="margin-top:16px">
      <table class="tbl">
        <thead><tr>
          <th>Perp</th>
          <th class="num">Bid</th>
          <th class="num">Ask</th>
          <th class="num">Last trade</th>
          <th class="num">Trades</th>
        </tr></thead>
        <tbody id="feed-body">
          <tr><td colspan="5" class="empty">connecting to the feed&hellip;</td></tr>
        </tbody>
      </table>
    </div>
    <p class="meta mono" id="feed-meta"></p>
  </section>

  <section class="panel" aria-labelledby="about-title">
    <div class="phead"><h2 id="about-title">What it is</h2></div>
    <div class="facts">
      <div><div class="fact-k">Coverage</div><div class="fact-v">All Kalshi crypto perpetuals &mdash; BTC, ETH, SOL, XRP, and more.</div></div>
      <div><div class="fact-k">Data</div><div class="fact-v">Top-of-book (best bid/ask) plus every executed trade.</div></div>
      <div><div class="fact-k">Transport</div><div class="fact-v">Binary multicast over the DoubleZero edge network.</div></div>
      <div><div class="fact-k">Decoding</div><div class="fact-v">Fixed-size wire format, decoded deterministically to normalized events.</div></div>
      <div><div class="fact-k">Benchmark baseline</div><div class="fact-v">Kalshi&rsquo;s own public perps WebSocket (<span class="mono">external-api-margin-ws.kalshi.com</span>) &mdash; the same data, the standard public way to get it.</div></div>
      <div><div class="fact-k">Method</div><div class="fact-v">One host, one monotonic clock; trades matched by exchange timestamp + price + size.</div></div>
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    Latency benchmark of the DoubleZero Kalshi perps edge feed vs Kalshi&rsquo;s public API. Measured on one host with a single monotonic clock; figures are live over a rolling window.
  </div>
</footer>

<script>
(function(){
  var lastState = null;

  function renderUpdated(){
    var el = document.getElementById('updated');
    if(!lastState || !lastState.updated_iso){ el.textContent = 'updated —'; return; }
    var secs = Math.max(0, Math.round((Date.now() - new Date(lastState.updated_iso).getTime())/1000));
    el.textContent = 'updated ' + secs + 's ago';
  }

  function soonerTxt(v){
    // v = dz - public in ms; negative = DoubleZero first (sooner).
    if(v == null || isNaN(v)) return '— ms';
    var s = -Number(v);
    return s >= 0 ? s.toFixed(1) + ' ms sooner' : Math.abs(s).toFixed(1) + ' ms slower';
  }

  function fmtNum(n){
    if(n == null || isNaN(n)) return '—';
    var v = Number(n), a = Math.abs(v);
    var dp = a >= 1000 ? 0 : (a >= 1 ? 2 : 6);
    return v.toLocaleString(undefined,{minimumFractionDigits:dp, maximumFractionDigits:dp});
  }

  function fmtUptime(s){
    s = Math.max(0, Math.floor(s||0));
    var h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
    return (h?h+'h ':'') + (h||m?m+'m ':'') + sec + 's';
  }

  function renderDzPill(state){
    var pill = document.getElementById('dzpill');
    var live = state.dz_feed === 'live';
    pill.textContent = 'feed: ' + (live ? 'live' : 'pending');
    pill.className = 'pill ' + (live ? 'live' : 'pending');
  }

  function renderScore(state){
    var L = state && state.latency;
    var gauge = document.getElementById('score-gauge');
    var wr = document.getElementById('score-winrate');
    var p50 = document.getElementById('score-p50');
    var statrow = document.getElementById('score-statrow');
    var note = document.getElementById('score-note');
    var ready = !!(L && typeof L.win_rate === 'number' && L.n > 0);
    if(!ready){
      gauge.style.setProperty('--pct','0'); wr.textContent = '—';
      p50.textContent = '— ms';
      statrow.textContent = 'matched — trades · rolling window';
      return;
    }
    gauge.style.setProperty('--pct', String(Math.max(0, Math.min(100, L.win_rate))));
    wr.textContent = L.win_rate.toFixed(0) + '%';
    p50.textContent = soonerTxt(L.p50_ms);
    statrow.textContent = 'matched ' + L.n + ' trades · ' + (L.window_min || 30) + '-min window';
    note.textContent = 'DoubleZero arrives first on ' + L.win_rate.toFixed(0) +
      '% of matched trades — one host, one monotonic clock, no cross-machine skew.';
  }

  function renderWinStrip(state){
    var L = state && state.latency;
    var wrap = document.getElementById('winstrip-wrap');
    var strip = document.getElementById('winstrip');
    var count = document.getElementById('ws-count');
    var recent = (L && Array.isArray(L.recent)) ? L.recent : [];
    if(!recent.length){ wrap.style.display = 'none'; return; }
    wrap.style.display = '';
    strip.innerHTML = recent.map(function(r){
      return '<div class="ws-cell' + (r.w ? ' win' : '') + '" title="' + r.d + ' ms"></div>';
    }).join('');
    var wins = recent.filter(function(r){ return r.w; }).length;
    count.textContent = wins + ' / ' + recent.length + ' DoubleZero first';
  }

  function renderLiveFeed(state){
    var d = state && state.dz_live;
    var stats = document.getElementById('feed-stats');
    var body = document.getElementById('feed-body');
    var meta = document.getElementById('feed-meta');
    if(!d || state.dz_feed !== 'live'){
      stats.style.display = 'none';
      body.innerHTML = '<tr><td colspan="5" class="empty">connecting to the feed…</td></tr>';
      meta.textContent = '';
      return;
    }
    stats.style.display = '';
    document.getElementById('feed-mkts').textContent = (d.market_count != null) ? d.market_count : '—';
    document.getElementById('feed-tps').textContent = (d.rates && d.rates.trades_per_s != null) ? d.rates.trades_per_s : '—';
    document.getElementById('feed-mps').textContent = (d.rates && d.rates.msgs_per_s != null) ? Math.round(d.rates.msgs_per_s) : '—';
    document.getElementById('feed-uptime').textContent = fmtUptime(d.uptime_s);

    var mk = d.markets || {};
    var keys = Object.keys(mk).sort();
    if(!keys.length){
      body.innerHTML = '<tr><td colspan="5" class="empty">no markets yet…</td></tr>';
    } else {
      body.innerHTML = keys.map(function(k){
        var v = mk[k];
        var last = '—';
        if(v.last_price != null){
          last = fmtNum(v.last_price);
          if(v.last_side){ last += ' <span style="color:var(--faint)">' + String(v.last_side).toUpperCase() + '</span>'; }
        }
        return '<tr><td>' + k + '</td>' +
          '<td class="num">' + fmtNum(v.bid) + '</td>' +
          '<td class="num">' + fmtNum(v.ask) + '</td>' +
          '<td class="num">' + last + '</td>' +
          '<td class="num">' + (v.trades != null ? v.trades : '—') + '</td></tr>';
      }).join('');
    }
    var tot = d.totals || {};
    meta.textContent = (d.metro || '') + ' edge node · ' +
      (tot.trades != null ? tot.trades : '—') + ' trades / ' +
      (tot.quotes != null ? tot.quotes : '—') + ' quotes decoded since start';
  }

  function render(state){
    lastState = state;
    renderDzPill(state);
    renderScore(state);
    renderWinStrip(state);
    renderLiveFeed(state);
    renderUpdated();
  }

  function poll(){
    fetch('/api/state').then(function(r){ return r.json(); }).then(render).catch(function(){});
  }

  poll();
  setInterval(renderUpdated, 1000);

  if(typeof EventSource !== 'undefined'){
    var es = new EventSource('/events');
    es.onmessage = function(ev){ try { render(JSON.parse(ev.data)); } catch(e) {} };
    es.onerror = function(){ es.close(); setInterval(poll, 3000); };
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
