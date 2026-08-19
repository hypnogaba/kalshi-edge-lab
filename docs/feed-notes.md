# Kalshi feed notes

(fill during Task 10)

## Kalshi WS message shapes

### Observed (demo)

Captured live from the Kalshi demo public WS. Raw lines also live in
`tests/data/kalshi_samples.jsonl` (lines 1-3).

```json
{"type":"subscribed","id":1,"msg":{"channel":"orderbook_delta","sid":1}}
{"type":"subscribed","id":1,"msg":{"channel":"trade","sid":2}}
{"type":"orderbook_snapshot","sid":1,"seq":1,"msg":{"market_ticker":"KXBTCD-26AUG2017-T73749.99","market_id":"ce3720ea-b877-4589-9250-757c7027f907"}}
```

Notes:
- Top-level `seq` lives on the message envelope; `market_ticker` lives inside `msg`.
- The demo environment has no real order flow: the observed `orderbook_snapshot` has an
  **empty book** — no `yes`/`no` arrays at all — and no `trade` or `orderbook_delta` messages
  ever arrive on demo. Both are structurally possible per the subscription acks above, but
  never observed with content.

### Documented (pending prod verification)

The shapes below are inferred from Kalshi's public API docs, not from a live capture (the demo
feed never produces them — see above). They are exercised by the decoder and by the test
fixture, but the exact field names must be **confirmed against a real prod capture** before
being treated as ground truth:

```json
{"type":"orderbook_snapshot","sid":1,"seq":2,"msg":{"market_ticker":"KXBTCD-X","yes":[[10,100],[11,50]],"no":[[20,30]]}}
{"type":"orderbook_delta","sid":1,"seq":3,"msg":{"market_ticker":"KXBTCD-X","price":40,"delta":-2,"side":"no"}}
{"type":"trade","sid":2,"msg":{"market_ticker":"KXBTCD-X","yes_price":52,"count":3,"taker_side":"yes","ts":1700}}
```

Fields to reverify against prod:
- `orderbook_snapshot.msg.yes` / `.no` — arrays of `[price, size]` levels.
- `orderbook_delta.msg.price` / `.delta` / `.side` — single price-level change.
- `trade.msg.yes_price` / `.count` / `.taker_side` — trade print fields (there may also be a
  `no_price` field for no-side prints; unverified on demo since no trades occur there).

### Market selection

Kalshi's BTC strike-ladder products come in a few series:
- `KXBTCD` — daily strike ladder (what the demo capture above used).
- `KXBTC` — the base/legacy BTC series.
- `KXBTC15M` — 15-minute strike ladder, expected to be the most actively traded in prod.

The final capture target market(s) will be chosen at prod-capture time based on which series
has real order flow.

## REST shapes (observed prod)

Captured live from the **public** Kalshi prod REST (`api.elections.kalshi.com`, no key) via
`sources/kalshi_rest/poller.py`. Real trade print:

```json
{"trade_id":"abc","ticker":"KXBTC-26AUG1912-B68550","taker_side":"yes",
 "yes_price_dollars":"0.0100","no_price_dollars":"0.9900",
 "count_fp":"50.00","created_time":"2026-08-19T15:37:39Z"}
```

Notes:
- Prices are **dollar strings** (`"0.0100"` → 1 cent), not integer cents like the WS feed.
  `count_fp` is a float-string, not an integer.
- `taker_side` picks which of `yes_price_dollars` / `no_price_dollars` is the trade price.
- Orderbook response shape: `{"orderbook":{"yes":[[price_cents,size],...],"no":[...]}}` —
  levels here *are* integer cents, unlike the trade endpoint.
- **Public REST orderbook depth is typically empty** (`yes`/`no` come back `null` or `[]`) even
  for actively-traded near-the-money markets. This was confirmed on the live smoke: 417 frames
  captured, 363 decoded to trade events, 0 to book-level events — trades printed continuously
  during the 30s window but no market returned non-empty depth. Book-level events are only
  produced when Kalshi does return levels; treat 0 as expected on public REST, not a bug.
