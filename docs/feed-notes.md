# Kalshi public perps WebSocket — message notes

Field notes for the public baseline the benchmark races against: Kalshi's perps WebSocket
(`wss://external-api-margin-ws.kalshi.com`). The DoubleZero edge feed's own wire format is the
binary Top-of-Book & Trades v3 spec, documented separately in
[`sources/dz_feed/README.md`](../sources/dz_feed/README.md) and the upstream
[`edge-feed-spec`](https://github.com/malbeclabs/edge-feed-spec).

## Subscription envelope

Captured sample lines live in `tests/data/kalshi_samples.jsonl`.

```json
{"type":"subscribed","id":1,"msg":{"channel":"orderbook_delta","sid":1}}
{"type":"subscribed","id":1,"msg":{"channel":"trade","sid":2}}
{"type":"orderbook_snapshot","sid":1,"seq":1,"msg":{"market_ticker":"...","market_id":"..."}}
```

Notes:
- Top-level `seq` lives on the message envelope; `market_ticker` lives inside `msg`.
- The `trade` channel is public; the socket is API-key authenticated once at the handshake.

## Message shapes the decoder handles

`sources/kalshi_ws/decoder.py` normalizes these into `common.event.Event`:

```json
{"type":"orderbook_snapshot","sid":1,"seq":2,"msg":{"market_ticker":"X","yes":[[10,100]],"no":[[20,30]]}}
{"type":"orderbook_delta","sid":1,"seq":3,"msg":{"market_ticker":"X","price":40,"delta":-2,"side":"no"}}
{"type":"trade","sid":2,"msg":{"market_ticker":"X","yes_price":52,"count":3,"taker_side":"yes","ts":1700}}
```

Fields:
- `orderbook_snapshot.msg.yes` / `.no` — arrays of `[price, size]` levels (integer cents).
- `orderbook_delta.msg.price` / `.delta` / `.side` — a single price-level change.
- `trade.msg.yes_price` / `.count` / `.taker_side` / `.ts` — trade print. The venue `ts` (plus
  price and count) is the match key against the edge feed, since the two feeds use different
  trade-id spaces (see `docs/methodology.md`).

## Match target

The benchmark targets Kalshi crypto perpetuals (`KXBTCPERP`, `KXETHPERP`, …) — the same
instruments the DoubleZero edge feed carries. Both feeds stamp each trade with the venue's own
execution timestamp, price, and contract count, which is what the matcher keys on.
