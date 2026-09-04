"""The stream page: two bots, one screen.

Deliberately not the same layout as the benchmark page. It has to stay legible
off a video capture from across a room, which is why the two rates carry the
page. That is not the same as making them enormous: at 104px against 13px
labels there was nothing in between, the two rates read as separate exhibits
rather than one comparison, and the head start -- which is the whole reason the
rates differ -- was set smaller than either of them. The scale below is
ordered by what matters: rate, then head start, then the labels that qualify
them. Same type and colour tokens as web/server.py so the two pages still look
like one product.

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
  body{margin:0; background:var(--ink); color:var(--fg); font-size:16px;
    font-family:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    -webkit-font-smoothing:antialiased}
  /* 1200px let the table columns drift apart until the rows read as scattered
     numbers rather than as a row. 1040 keeps them together on a wide screen. */
  .wrap{max-width:1040px; margin:0 auto; padding:0 28px}
  .mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums}
  header{border-bottom:1px solid var(--line)}
  .bar{display:flex; align-items:center; gap:14px; min-height:62px; padding:12px 0;
       flex-wrap:wrap}
  h1{font-family:"Archivo",system-ui,sans-serif; font-weight:800; font-size:21px;
     letter-spacing:-.01em; margin:0}
  .spacer{flex:1}
  .pill{font-family:"IBM Plex Mono"; font-size:12px; letter-spacing:.06em;
    text-transform:uppercase; padding:5px 12px; border-radius:999px;
    border:1px solid var(--line); color:var(--muted); white-space:nowrap}
  .pill.on{border-color:var(--win); color:var(--win)}
  .pill.off{border-style:dashed; color:var(--faint)}
  main{padding:30px 0 26px}
  .lede{color:var(--muted); max-width:66ch; margin:0 0 26px; line-height:1.65;
        font-size:15.5px}
  .lede b{color:var(--fg); font-weight:600}
  /* One panel, three cells. Two bordered boxes with loose text between them read
     as three separate exhibits; the point is a single comparison, so the divider
     lines do the separating and the head start sits on the seam between the two
     numbers it explains. */
  .duo{display:grid; grid-template-columns:1fr auto 1fr; align-items:stretch;
       background:var(--panel); border:1px solid var(--line); border-radius:16px;
       overflow:hidden}
  .side{padding:24px 26px 22px; min-width:0}
  .side.fast{background:color-mix(in srgb, var(--win) 5%, var(--panel))}
  .side h2{font-family:"IBM Plex Mono"; font-size:11.5px; letter-spacing:.12em;
    text-transform:uppercase; color:var(--muted); font-weight:500; margin:0}
  .side.fast h2{color:var(--win)}
  .big{font-family:"Archivo",system-ui,sans-serif; font-weight:800;
       font-size:clamp(38px, 5vw, 56px); line-height:1.05; letter-spacing:-.03em;
       margin:10px 0 6px}
  .side.fast .big{color:var(--win)}
  .unit{color:var(--faint); font-size:13px; line-height:1.5; max-width:32ch}
  .versus{display:flex; flex-direction:column; align-items:center; justify-content:center;
          gap:4px; padding:24px 22px; min-width:132px;
          border-left:1px solid var(--line); border-right:1px solid var(--line)}
  .versus .lead{font-family:"Archivo"; font-weight:800; font-size:30px;
                letter-spacing:-.02em; line-height:1}
  .versus .cap{font-family:"IBM Plex Mono"; font-size:10.5px; letter-spacing:.1em;
    text-transform:uppercase; color:var(--faint); text-align:center; line-height:1.5}
  @media (max-width:760px){
    .duo{grid-template-columns:1fr}
    .versus{border-left:0; border-right:0;
            border-top:1px solid var(--line); border-bottom:1px solid var(--line);
            flex-direction:row; gap:10px; padding:14px}
    .versus .cap{text-align:left}
  }
  .split{display:flex; height:10px; border-radius:999px; overflow:hidden; margin:20px 0 0;
         border:1px solid var(--line)}
  .split i{display:block; height:100%}
  .split .a{background:var(--win)}
  .split .b{background:var(--lose)}
  .split .c{background:var(--panel-2)}
  .splitkey{display:flex; gap:20px; margin:9px 0 0; font-family:"IBM Plex Mono";
    font-size:11.5px; color:var(--faint); flex-wrap:wrap}
  .dot{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:7px}
  h3{font-family:"Archivo"; font-weight:700; font-size:16px; margin:32px 0 10px}
  table{width:100%; border-collapse:collapse; font-family:"IBM Plex Mono"; font-size:13px}
  th,td{text-align:left; padding:8px 14px; border-bottom:1px solid var(--line); white-space:nowrap}
  /* The two verdict columns carry the story, so they get the room; market and
     numbers are as narrow as their content. */
  th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){width:34%}
  th{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint); font-weight:500}
  td.num,th.num{text-align:right; font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:0}
  .tag{display:inline-block; padding:2px 8px; border-radius:6px; font-size:11.5px;
       border:1px solid var(--line); color:var(--muted)}
  .tag.got{border-color:var(--win); color:var(--win)}
  .tag.lost{border-color:var(--lose); color:var(--lose)}
  .tag.idle{color:var(--idle)}
  /* overflow-x only: a narrow screen scrolls the table sideways rather than
     squashing the two verdict columns. Setting overflow-x alone would compute
     overflow-y to auto as well and add a scrollbar that is never needed. */
  .card{background:var(--panel); border:1px solid var(--line); border-radius:16px;
        overflow-x:auto; overflow-y:hidden}
  .empty{padding:26px 16px; color:var(--faint); font-family:"IBM Plex Mono"; font-size:14px}
  footer{border-top:1px solid var(--line); margin-top:34px; padding:20px 0 36px;
         color:var(--faint); font-size:13.5px; line-height:1.7; max-width:78ch}
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
      <div class="cap">median<br>head start</div>
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
