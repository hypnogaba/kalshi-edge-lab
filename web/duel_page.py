"""The stream page: two bots, one screen.

Deliberately not the same layout as the benchmark page. This one is built to be
read off a video capture from across a room: dark, few numbers, each one large.
Same type and colour tokens as web/server.py so the two still look like one
product.

It states its own limits on screen, because a number that needs a caveat spoken
out loud will be quoted without it.
"""

DUEL_HTML = """<!doctype html>
<html lang="en" data-theme="dark">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The edge, spent</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root{
    --ink:#09090A; --panel:#141416; --panel-2:#1B1C1F; --line:rgba(255,255,255,.14);
    --fg:#ECEDEF; --muted:#A0A2A9; --faint:#6C6E76;
    --win:#3AD699; --lose:#E5484D; --idle:#6C6E76;
  }
  *{box-sizing:border-box}
  @media (prefers-reduced-motion: reduce){ *{transition:none!important} }
  body{margin:0; background:var(--ink); color:var(--fg); font-size:18px;
    font-family:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}
  .wrap{max-width:1200px; margin:0 auto; padding:0 32px}
  .mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums}
  header{border-bottom:1px solid var(--line)}
  .bar{display:flex; align-items:center; gap:16px; height:78px; flex-wrap:wrap}
  h1{font-family:"Archivo",system-ui,sans-serif; font-weight:800; font-size:24px;
     letter-spacing:-.01em; margin:0}
  .spacer{flex:1}
  .pill{font-family:"IBM Plex Mono"; font-size:12px; letter-spacing:.06em;
    text-transform:uppercase; padding:5px 12px; border-radius:999px;
    border:1px solid var(--line); color:var(--muted); white-space:nowrap}
  .pill.on{border-color:var(--win); color:var(--win)}
  .pill.off{border-style:dashed; color:var(--faint)}
  main{padding:36px 0 28px}
  .lede{color:var(--muted); max-width:72ch; margin:0 0 30px; line-height:1.6}
  .lede b{color:var(--fg); font-weight:600}
  .duo{display:grid; grid-template-columns:1fr auto 1fr; gap:24px; align-items:stretch}
  .side{background:var(--panel); border:1px solid var(--line); border-radius:18px;
        padding:30px 32px 26px}
  .side.fast{border-color:color-mix(in srgb, var(--win) 45%, var(--line))}
  .side h2{font-family:"IBM Plex Mono"; font-size:13px; letter-spacing:.12em;
    text-transform:uppercase; color:var(--muted); font-weight:500; margin:0 0 6px}
  .side.fast h2{color:var(--win)}
  .big{font-family:"Archivo",system-ui,sans-serif; font-weight:800; font-size:104px;
       line-height:1; letter-spacing:-.03em; margin:8px 0 4px}
  .side.fast .big{color:var(--win)}
  .unit{color:var(--faint); font-size:15px; font-family:"IBM Plex Mono"}
  .versus{display:flex; flex-direction:column; align-items:center; justify-content:center;
          gap:6px; padding:0 6px; min-width:150px}
  .versus .lead{font-family:"Archivo"; font-weight:800; font-size:40px; letter-spacing:-.02em}
  .versus .cap{font-family:"IBM Plex Mono"; font-size:11px; letter-spacing:.1em;
    text-transform:uppercase; color:var(--faint); text-align:center; line-height:1.5}
  .split{display:flex; height:12px; border-radius:999px; overflow:hidden; margin:26px 0 0;
         border:1px solid var(--line)}
  .split i{display:block; height:100%}
  .split .a{background:var(--win)}
  .split .b{background:var(--lose)}
  .split .c{background:var(--panel-2)}
  .splitkey{display:flex; gap:22px; margin:10px 0 0; font-family:"IBM Plex Mono";
    font-size:12px; color:var(--faint); flex-wrap:wrap}
  .dot{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:7px}
  h3{font-family:"Archivo"; font-weight:700; font-size:18px; margin:38px 0 12px}
  table{width:100%; border-collapse:collapse; font-family:"IBM Plex Mono"; font-size:14px}
  th,td{text-align:left; padding:11px 14px; border-bottom:1px solid var(--line); white-space:nowrap}
  th{font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint); font-weight:500}
  td.num,th.num{text-align:right; font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:0}
  .tag{display:inline-block; padding:3px 9px; border-radius:6px; font-size:12px;
       border:1px solid var(--line); color:var(--muted)}
  .tag.got{border-color:var(--win); color:var(--win)}
  .tag.lost{border-color:var(--lose); color:var(--lose)}
  .tag.idle{color:var(--idle)}
  .card{background:var(--panel); border:1px solid var(--line); border-radius:16px; overflow:hidden}
  .empty{padding:26px 16px; color:var(--faint); font-family:"IBM Plex Mono"; font-size:14px}
  footer{border-top:1px solid var(--line); margin-top:40px; padding:22px 0 40px;
         color:var(--faint); font-size:14px; line-height:1.7}
  footer b{color:var(--muted); font-weight:600}
</style>
<header><div class="wrap bar">
  <h1>The edge, spent</h1>
  <span class="pill" id="mode">paper</span>
  <span class="pill" id="market">waiting</span>
  <span class="spacer"></span>
  <span class="pill off" id="live">waiting for the feed</span>
</div></header>

<main class="wrap">
  <p class="lede">
    One machine, one clock, two pipes. The <b>same strategy</b> runs twice: one copy
    is fed by the DoubleZero edge feed, the other by Kalshi's public WebSocket.
    Both react to the same print. Both are filled against the <b>same order book</b>,
    each judged at the moment its own order could have arrived. The only
    difference between them is when they found out.
  </p>

  <div class="duo">
    <section class="side">
      <h2>Public internet</h2>
      <div class="big mono" id="pubRate">\u2026</div>
      <div class="unit">of shared chances taken at the price it wanted</div>
    </section>
    <div class="versus">
      <div class="lead mono" id="lead">\u2026</div>
      <div class="cap">median head start<br>over the public feed</div>
    </div>
    <section class="side fast">
      <h2>DoubleZero edge</h2>
      <div class="big mono" id="dzRate">\u2026</div>
      <div class="unit">of the same chances, same rule, same book</div>
    </section>
  </div>

  <div class="split" id="split"><i class="c" style="flex:1"></i></div>
  <div class="splitkey">
    <span><i class="dot" style="background:var(--win)"></i><span id="kOnlyDz">DoubleZero only</span></span>
    <span><i class="dot" style="background:var(--lose)"></i><span id="kOnlyPub">public only</span></span>
    <span><i class="dot" style="background:var(--panel-2)"></i><span id="kBoth">both</span></span>
    <span id="kWindow"></span>
  </div>

  <h3>Last decisions, side by side</h3>
  <div class="card"><div id="tableWrap" class="empty">waiting for the first shared chance</div></div>
</main>

<footer class="wrap">
  <b>What this is.</b> A latency instrument, not a profitable strategy. The rule
  crosses the spread on purpose, so its own mark-out is negative for both bots;
  what speed changes is whether the quote is still there.
  <span id="honesty"></span>
</footer>

<script>
const $ = id => document.getElementById(id);
const pct = v => v === null || v === undefined ? "\u2026" : v.toFixed(1) + "%";

function tag(side){
  if(!side || !side.acted) return '<span class="tag idle">did not act</span>';
  return side.filled ? '<span class="tag got">got the price</span>'
                     : '<span class="tag lost">quote gone</span>';
}

function rows(recent){
  if(!recent || !recent.length) return '<div class="empty">waiting for the first shared chance</div>';
  const body = recent.map(d => {
    const lead = d.lead_ms === undefined ? "" : d.lead_ms.toFixed(1) + " ms";
    return `<tr>
      <td>${d.market}</td>
      <td class="num">${d.trigger_size.toLocaleString()}</td>
      <td class="num">${d.trigger_price.toLocaleString()}</td>
      <td>${tag(d.public)}</td>
      <td>${tag(d.doublezero)}</td>
      <td class="num">${lead}</td></tr>`;
  }).join("");
  return `<table><thead><tr>
    <th>market</th><th class="num">print</th><th class="num">at</th>
    <th>public</th><th>doublezero</th><th class="num">head start</th>
  </tr></thead><tbody>${body}</tbody></table>`;
}

async function tick(){
  let s;
  try { s = await (await fetch("/api/duel", {cache:"no-store"})).json(); }
  catch(e) { return; }
  if(!s || !s.head_to_head){ $("live").textContent = "waiting for the feed"; return; }
  const h = s.head_to_head;
  $("live").textContent = "live"; $("live").className = "pill on";
  $("mode").textContent = s.mode || "paper";
  const markets = s.markets || [];
  $("market").textContent = markets.length ? markets.length + " crypto perps" : "waiting";
  $("market").title = markets.join(" · ");
  $("dzRate").textContent = pct(h.dz_fill_rate);
  $("pubRate").textContent = pct(h.public_fill_rate);
  $("lead").textContent = h.median_lead_ms === null ? "\u2026"
      : (Math.abs(h.median_lead_ms).toFixed(1) + " ms");

  const n = h.n || 0;
  const parts = [["a", h.dz_only_filled], ["b", h.public_only_filled],
                 ["c", h.both_filled + h.neither_filled]];
  $("split").innerHTML = n
    ? parts.map(([c, v]) => `<i class="${c}" style="flex:${v || 0}"></i>`).join("")
    : '<i class="c" style="flex:1"></i>';
  $("kOnlyDz").textContent = `DoubleZero only: ${h.dz_only_filled}`;
  $("kOnlyPub").textContent = `public only: ${h.public_only_filled}`;
  $("kBoth").textContent = `same outcome: ${h.both_filled + h.neither_filled}`;
  $("kWindow").textContent = `${n} shared chances · last ${Math.round(h.window_min/60)}h`;
  $("tableWrap").innerHTML = rows(s.recent);
  $("honesty").textContent =
    ` Paper fills, no fees and no queue position. Both bots get the same `
    + `${s.reaction_ms} ms to get an order on the wire, and marked out `
    + `${Math.round(s.markout_ms)} ms later.`;
}
tick(); setInterval(tick, 1000);
</script>
"""
