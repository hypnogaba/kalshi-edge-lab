"""Public dashboard for the DoubleZero Kalshi crypto-perps edge feed.

A read-only FastAPI app that serves a self-contained monochrome page showing,
live: (1) a latency benchmark of the DoubleZero edge feed vs Kalshi's public
perps WebSocket, and (2) the live decoded feed for every Kalshi crypto
perpetual. It only reads two JSON snapshots written by the two collector
services and never places orders or touches funds:
  - data/dz_latency.json     (scripts.dz_latency_race)
  - data/dz_feed_state.json  (scripts.dz_live_feed)
  - data/demo_state.json     (demo.runner, served at /duel)
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

from web.duel_page import DUEL_HTML

REFRESH_SECONDS = float(os.environ.get("EDGE_WEB_INTERVAL", "2"))
DZ_FEED_STATE_PATH = Path("data/dz_feed_state.json")
DZ_LATENCY_PATH = Path("data/dz_latency.json")
DEMO_STATE_PATH = Path("data/demo_state.json")
DZ_FRESH_SECONDS = 15  # a snapshot older than this is treated as not-live

STATE: dict = {
    "updated_ns": None,
    "updated_iso": None,
    "dz_feed": "pending",
    "dz_live": None,
    "latency": None,
    "duel": None,
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
    STATE["duel"] = _read_fresh(DEMO_STATE_PATH)
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


@app.get("/api/duel")
async def get_duel() -> JSONResponse:
    """The two-bot state on its own, for the /duel page's 1 Hz poll."""
    return JSONResponse(STATE["duel"] or {})


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_PAGE_HTML)


@app.get("/duel", response_class=HTMLResponse)
async def duel() -> HTMLResponse:
    return HTMLResponse(DUEL_HTML)


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
  /* Absolute-latency chain: each hop a trade makes, top to bottom. */
  .chain{margin:18px 0 0; border-left:2px solid var(--line); padding-left:0}
  .chain-node{position:relative; padding:0 0 0 22px; margin-left:-1px}
  .chain-node::before{content:""; position:absolute; left:-7px; top:6px;
    width:12px; height:12px; border-radius:50%; background:var(--panel);
    border:2px solid var(--faint)}
  .chain-node.is-end::before{background:var(--accent); border-color:var(--accent)}
  .chain-name{font-weight:600; font-size:15px; line-height:1.3}
  .chain-where{color:var(--faint); font-size:12.5px; margin-top:1px}
  .chain-hop{display:flex; align-items:baseline; gap:12px; padding:12px 0 12px 22px;
    margin-left:-1px; color:var(--muted); font-size:13.5px}
  .chain-ms{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums;
    font-size:19px; font-weight:600; color:var(--fg); min-width:86px; letter-spacing:-.01em}
  .chain-total{display:flex; align-items:baseline; justify-content:space-between;
    gap:14px; flex-wrap:wrap; margin-top:18px; padding-top:16px; border-top:1px solid var(--line)}
  .chain-total-k{font-size:13.5px; color:var(--muted)}
  .chain-total-v{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums;
    font-size:30px; font-weight:700; letter-spacing:-.02em}
  .vs-row{display:flex; align-items:baseline; justify-content:space-between; gap:14px;
    flex-wrap:wrap; margin-top:10px}
  .vs-k{font-size:13.5px; color:var(--muted)}
  .vs-v{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums;
    font-size:19px; color:var(--muted)}
  .setting{margin-top:-4px}
  /* Two distributions on one axis: a median says where the middle is, the
     shape says whether the paths are separate populations at all. */
  .dist{margin-top:20px}
  .dist-head{display:flex; align-items:baseline; justify-content:space-between;
    gap:14px; flex-wrap:wrap; margin-bottom:10px}
  .dist-title{font-size:13.5px; color:var(--muted)}
  .dist-key{display:flex; gap:14px; font-size:11.5px; color:var(--faint);
    font-family:"IBM Plex Mono",ui-monospace,monospace}
  .sw{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:5px;
    vertical-align:middle}
  .sw-dz{background:var(--accent)}
  .sw-pub{background:var(--faint)}
  .dist svg{display:block; width:100%; height:auto; overflow:visible}
  .pct th, .pct td{white-space:nowrap}
  .pct tbody tr td:first-child{color:var(--fg)}
  .pct .lead td{color:var(--accent); border-top:1px solid var(--line)}
  .pct .lead td:first-child{color:var(--muted)}
  /* The method is kept out of the way but one click from anyone checking it. */
  .method{margin:18px 0 0; border-top:1px solid var(--line); padding-top:14px}
  .method summary{cursor:pointer; color:var(--faint); font-size:12.5px;
    letter-spacing:.02em; list-style:none; user-select:none; width:fit-content}
  .method summary::-webkit-details-marker{display:none}
  .method summary::before{content:"+ "; font-family:"IBM Plex Mono",monospace}
  .method[open] summary::before{content:"– "}
  .method summary:hover{color:var(--fg)}
  .setup{display:grid; grid-template-columns:140px 1fr; gap:9px 20px;
    margin:14px 0 0; font-size:12.5px; line-height:1.6}
  .setup dt{color:var(--faint); font-size:11px; letter-spacing:.03em;
    text-transform:uppercase; font-weight:600; padding-top:1px}
  .setup dd{margin:0; color:var(--muted)}
  .setup dd b{color:var(--fg); font-weight:600}
  .setup .mono{font-size:11.5px}
  @media (max-width:640px){ .setup{grid-template-columns:1fr; gap:2px 0}
    .setup dd{margin:0 0 10px} }
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

  <section class="panel" aria-labelledby="abs-title">
    <div class="phead">
      <h2 id="abs-title">How long DoubleZero actually takes</h2>
    </div>
    <p class="explainer">The panel above says how much <i>sooner</i> DoubleZero is. This one says how long the trip takes. Every Kalshi trade carries the exchange&rsquo;s own execution timestamp, so the clock starts at the venue rather than at our door.</p>

    <p class="explainer setting">One server in Europe, listening at DoubleZero&rsquo;s Frankfurt edge. Kalshi sits in AWS us-east-2, an ocean away &mdash; <b>106 ms</b> round trip from here, against <b>2.9 ms</b> to the DoubleZero edge.</p>

    <div class="chain" id="abs-chain" style="display:none">
      <div class="chain-node">
        <div class="chain-name">Kalshi stamps the trade</div>
        <div class="chain-where">the execution timestamp the venue puts in the message</div>
      </div>
      <div class="chain-hop">
        <span class="chain-ms" id="abs-leg1">&mdash;</span>
        <span>until DoubleZero stamps the frame it sends</span>
      </div>
      <div class="chain-node">
        <div class="chain-name">DoubleZero sends the frame</div>
        <div class="chain-where">the send timestamp in the frame header</div>
      </div>
      <div class="chain-hop">
        <span class="chain-ms" id="abs-leg2">&mdash;</span>
        <span>in flight, by those two stamps</span>
      </div>
      <div class="chain-node is-end">
        <div class="chain-name">The packet lands on our network card</div>
        <div class="chain-where">stamped by the kernel, on a clock we check against public time servers</div>
      </div>
      <div class="chain-total">
        <span class="chain-total-k">Venue stamp &rarr; our network card, over DoubleZero <span class="mono" id="abs-n" style="color:var(--faint)"></span></span>
        <span class="chain-total-v" id="abs-total">&mdash;</span>
      </div>

      <div class="dist">
        <div class="dist-head">
          <span class="dist-title">Where every trade landed</span>
          <span class="dist-key">
            <span><i class="sw sw-dz"></i>DoubleZero</span>
            <span><i class="sw sw-pub"></i>public WebSocket</span>
          </span>
        </div>
        <div id="abs-hist"></div>
      </div>

      <div class="card" style="margin-top:14px">
        <table class="tbl pct">
          <thead><tr>
            <th>Latency, venue stamp to our card</th>
            <th class="num">P50</th><th class="num">P90</th>
            <th class="num">P95</th><th class="num">P99</th><th class="num">Max</th>
          </tr></thead>
          <tbody id="abs-pct"></tbody>
        </table>
      </div>
      <p class="subnote" style="margin-top:10px">A US-East to Frankfurt hop cannot beat about 43&ndash;47 ms through real fibre, so the floor of this chart is physics, not engineering. The tail is where the two paths part company.</p>
      <details class="method">
        <summary>How this is measured</summary>
        <dl class="setup">
          <dt>The DoubleZero side</dt>
          <dd>Multicast group <span class="mono">233.84.178.3</span>, Top-of-Book &amp; Trades, taken off the <span class="mono">doublezero1</span> tunnel with AF_PACKET. DoubleZero reports the edge device as <span class="mono">fr2-dzx-001</span>, metro Frankfurt; the tunnel peer resolves to Frankfurt am Main.</dd>
          <dt>The public side</dt>
          <dd>Kalshi&rsquo;s own perpetuals WebSocket, <span class="mono">external-api-margin-ws.kalshi.com</span>, which anyone can connect to.</dd>
          <dt>Arrival</dt>
          <dd>The kernel&rsquo;s <span class="mono">SO_TIMESTAMPNS</span> stamp, taken as the packet lands on the interface, not a clock read after our code wakes up.</dd>
          <dt>Sample</dt>
          <dd>Only trades seen on <i>both</i> feeds, joined on the venue timestamp, price and size, so the two rows describe the same prints.</dd>
          <dt>Limits</dt>
          <dd id="abs-caveat"></dd>
        </dl>
      </details>
    </div>
    <p class="explainer" id="abs-waiting">Measuring&hellip; the first matched trades are still coming in.</p>
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
    var wm = L.window_min || 30;
    var win = wm >= 60 ? (wm / 60) + 'h' : wm + '-min';
    statrow.textContent = 'matched ' + L.n + ' trades · ' + win + ' window';
    note.textContent = 'DoubleZero arrives first on ' + L.win_rate.toFixed(0) +
      '% of matched trades — one host, one monotonic clock, no cross-machine skew.';
  }

  function ms(v){ return (typeof v === 'number') ? v.toFixed(1) + ' ms' : '—'; }

  // Two histograms sharing one x axis and one y scale, drawn as small
  // multiples rather than overlaid: overlapping translucent bars hide exactly
  // the region where the two distributions meet, which is the region worth
  // seeing. Counts past the axis get their own labelled marker so a heavy
  // tail cannot be lost off the right edge.
  function histSvg(h){
    if(!h) return '';
    var W = 720, ROW = 54, PAD_L = 74, PAD_R = 34, AX = 20, GAP = 14;
    var H = ROW * 2 + GAP + AX;
    var n = h.dz.length;
    var peak = 0;
    for(var i = 0; i < n; i++){
      if(h.dz[i] > peak) peak = h.dz[i];
      if(h.public[i] > peak) peak = h.public[i];
    }
    if(peak <= 0) return '';
    var plotW = W - PAD_L - PAD_R, bw = plotW / n;

    function row(bins, over, y, colour, label){
      var s = '<text x="' + (PAD_L - 10) + '" y="' + (y + ROW - 4) +
              '" text-anchor="end" class="hx" fill="var(--muted)">' + label + '</text>';
      for(var i = 0; i < n; i++){
        if(!bins[i]) continue;
        var bh = Math.max(1, (bins[i] / peak) * (ROW - 6));
        s += '<rect x="' + (PAD_L + i * bw).toFixed(2) + '" y="' + (y + ROW - bh).toFixed(2) +
             '" width="' + Math.max(1, bw - 0.6).toFixed(2) + '" height="' + bh.toFixed(2) +
             '" fill="' + colour + '" rx="0.5"><title>' +
             (h.lo_ms + i * h.width_ms).toFixed(0) + '–' +
             (h.lo_ms + (i + 1) * h.width_ms).toFixed(0) + ' ms: ' + bins[i] + '</title></rect>';
      }
      if(over > 0){
        s += '<text x="' + (W - PAD_R + 5) + '" y="' + (y + ROW - 1) +
             '" class="hx" fill="' + colour + '">+' + over + '</text>';
      }
      return s;
    }

    var g = row(h.dz, h.dz_over, 0, 'var(--accent)', 'DoubleZero');
    g += row(h.public, h.public_over, ROW + GAP, 'var(--faint)', 'public WS');

    var axisY = ROW * 2 + GAP;
    g += '<line x1="' + PAD_L + '" y1="' + axisY + '" x2="' + (W - PAD_R) +
         '" y2="' + axisY + '" stroke="var(--line)"/>';
    for(var t = h.lo_ms; t <= h.hi_ms; t += 10){
      var x = PAD_L + ((t - h.lo_ms) / (h.hi_ms - h.lo_ms)) * plotW;
      g += '<line x1="' + x.toFixed(1) + '" y1="' + axisY + '" x2="' + x.toFixed(1) +
           '" y2="' + (axisY + 4) + '" stroke="var(--line)"/>' +
           '<text x="' + x.toFixed(1) + '" y="' + (axisY + 15) +
           '" text-anchor="middle" class="hx" fill="var(--faint)">' + t + '</text>';
    }
    g += '<text x="' + (W - PAD_R) + '" y="' + (axisY + 15) +
         '" text-anchor="end" class="hx" fill="var(--faint)">ms</text>';

    return '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
           'aria-label="Latency distribution, DoubleZero against the public WebSocket">' +
           '<style>.hx{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px}</style>' +
           g + '</svg>';
  }

  function pctRows(A){
    var keys = ['p50_ms','p90_ms','p95_ms','p99_ms','max_ms'];
    function cells(o){
      return keys.map(function(k){
        return '<td class="num mono">' + (o && typeof o[k] === 'number' ? o[k].toFixed(1) : '—') + '</td>';
      }).join('');
    }
    var dz = A.dz_total, pub = A.public_total;
    var lead = keys.map(function(k){
      var d = (dz && pub && typeof dz[k] === 'number' && typeof pub[k] === 'number')
        ? pub[k] - dz[k] : null;
      return '<td class="num mono">' + (d === null ? '—' : (d >= 0 ? '+' : '') + d.toFixed(1)) + '</td>';
    }).join('');
    return '<tr><td>DoubleZero</td>' + cells(dz) + '</tr>' +
           '<tr><td>Public WebSocket</td>' + cells(pub) + '</tr>' +
           '<tr class="lead"><td>DoubleZero ahead by</td>' + lead + '</tr>';
  }

  function renderAbsolute(state){
    var L = state && state.latency;
    var A = L && L.absolute;
    var chain = document.getElementById('abs-chain');
    var waiting = document.getElementById('abs-waiting');
    var ok = !!(A && A.dz_total && A.public_total && A.n > 0);
    if(!ok){ chain.style.display = 'none'; waiting.style.display = ''; return; }
    chain.style.display = ''; waiting.style.display = 'none';

    var leg1 = A.exch_to_pub, leg2 = A.dz_transport;
    document.getElementById('abs-leg1').textContent = leg1 ? ms(leg1.p50_ms) : '—';
    document.getElementById('abs-leg2').textContent = leg2 ? ms(leg2.p50_ms) : '—';
    document.getElementById('abs-total').textContent = ms(A.dz_total.p50_ms);
    document.getElementById('abs-n').textContent = '· median of ' + A.n + ' matched trades';
    document.getElementById('abs-hist').innerHTML = histSvg(A.hist);
    document.getElementById('abs-pct').innerHTML = pctRows(A);

    // The number is only as good as the clock it was measured against, and the
    // two feeds are not stamped at the same depth. Both are stated, not hidden.
    var c = A.clock;
    var clockTxt = c
      ? 'our clock is <b>' + Math.abs(c.offset_ms).toFixed(2) + ' ms</b> off true time (' +
        c.source + ', stratum ' + c.stratum + ', worst case ' + c.error_ms.toFixed(1) + ' ms)'
      : 'our clock offset could not be read just now';
    var lead = (typeof L.p50_ms === 'number') ? Math.abs(L.p50_ms).toFixed(1) + ' ms' : '—';
    document.getElementById('abs-caveat').innerHTML =
      'The total rests on two clocks, Kalshi&rsquo;s and ours &mdash; ' + clockTxt + '. ' +
      'Splitting it into legs also trusts the publisher&rsquo;s clock, which we cannot check, ' +
      'so the total is the measurement and the split is DoubleZero&rsquo;s account of it. ' +
      'Kalshi stamps in whole milliseconds, so totals are up to 1 ms high, never low. ' +
      'DoubleZero is stamped by the kernel while a WebSocket message only exists after decoding, ' +
      'which flatters DoubleZero by a few tenths; the head-to-head race above stamps both sides ' +
      'the same way and puts the lead at ' + lead + '.';
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
    renderAbsolute(state);
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
