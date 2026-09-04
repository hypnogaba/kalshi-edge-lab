# Kalshi public perps WebSocket — message notes

Field notes for the public baseline the benchmark races against: Kalshi's perps WebSocket
(`wss://external-api-margin-ws.kalshi.com`). The DoubleZero edge feed's own wire format is the
binary Top-of-Book & Trades v3 spec, documented separately in
[`sources/dz_feed/README.md`](../sources/dz_feed/README.md) and the upstream
[`edge-feed-spec`](https://github.com/malbeclabs/edge-feed-spec).

## Subscription envelope

Captured sample lines live in `tests/data/margin_trades.jsonl`, recorded straight off the
live socket. The older `kalshi_samples.jsonl` came from the other socket
(`/trade-api/ws/v2`, Kalshi's event markets) and was dropped once the decoder was
repointed here: keeping fixtures for a schema nothing decodes is how the decoder came
to read `yes_price` from a feed that sends `price` for months without a red test.

```json
{"type":"subscribed","id":1,"msg":{"channel":"trade","sid":1}}
{"type":"trade","sid":1,"seq":1,"msg":{"trade_id":"0721c72a-8859-b8d2-6603-25bd482f0d18","market_ticker":"KXBTCPERP","price":"8.0961","count":"617.00","taker_side":"ask","ts_ms":1788502115168}}
```

Notes:
- Top-level `seq` lives on the message envelope; `market_ticker` lives inside `msg`.
- The `trade` channel is public; the socket is API-key authenticated once at the handshake.
- **`seq` is not a trade id.** It counts messages on the subscription — 1, 2, 3 across
  consecutive trades on any market. The venue's own trade id is the UUID in
  `msg.trade_id`. The edge feed's `seq` is a `u64` trade id, so the two are different id
  spaces and must never be matched against each other (see `race/match.py`).

## Message shapes the decoder handles

`sources/kalshi_ws/decoder.py` normalizes trades into `common.event.Event`. Fields:

- `msg.price` — **a string**, and dollars per **contract**, not per unit of the underlying.
  `"8.0961"` on `KXBTCPERP` (contract `1e-4`) is $80,961 per BTC. Converting needs the
  market's contract size, which only the edge feed publishes, so the decoder leaves it alone
  (see `sources/dz_feed/contract_sizes.py`).
- `msg.count` — also a string, `"617.00"`, in contracts.
- `msg.taker_side` — `"bid"` / `"ask"`, **not** `"yes"` / `"no"`. Measured over 219 live
  trades: `bid` printed at or above the ask, so `bid` is an aggressive BUY.
- `msg.ts_ms` — the venue's execution timestamp, in whole milliseconds. This, with price and
  count, is the match key against the edge feed.

The event-market socket (`/trade-api/ws/v2`) sends `yes_price` / `no_price`, `taker_side`
`yes`/`no` and `ts` in seconds. Those names are real there and wrong here; reading them off
this feed returns `None` for every price, and a matcher then skips every price comparison in
silence. Book reconstruction is not in the decoder either — the top of book has to be rebuilt
from `orderbook_snapshot` + `orderbook_delta`, which `demo/public_feed.py` does.

## Match target

The benchmark targets Kalshi crypto perpetuals (`KXBTCPERP`, `KXETHPERP`, …) — the same
instruments the DoubleZero edge feed carries. Both feeds stamp each trade with the venue's own
execution timestamp, price, and contract count, which is what the matcher keys on.
