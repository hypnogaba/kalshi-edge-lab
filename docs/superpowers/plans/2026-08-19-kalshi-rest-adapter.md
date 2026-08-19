# Keyless Kalshi REST Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A third source adapter, `sources/kalshi_rest/`, that polls the **public** Kalshi prod REST (no key) and normalizes real BTC trades + order books into the same `Event` stream, so Phase 2 can develop against real prod data before a prod WS key exists.

**Architecture:** Same source-adapter contract as `sources/kalshi_ws/`. A thin REST client → a poller that writes tagged raw frames to disk (via `common.storage`) and → a `decode(raw, t_arrival_ns) -> list[Event]` that dispatches on the frame envelope. A pure market-selector picks near-the-money strikes using the Binance BTC spot.

**Tech Stack:** Python 3.12, httpx, orjson, existing `common/` modules. Tests via `httpx.MockTransport` (no network in unit tests) + one live smoke against public prod trades.

**Verified facts (see design §12):** prod REST is public. Real trade shape: `{"trade_id","ticker","taker_side":"yes|no","yes_price_dollars":"0.0100","no_price_dollars":"0.9900","count_fp":"50.00","created_time"}` (dollar strings, float-string count). Orderbook: `{"orderbook":{"yes":[[price_cents,size],...],"no":[...]}}` (depth often empty on public REST — handle empty gracefully).

---

## File Structure

| File | Responsibility |
|---|---|
| `sources/kalshi_rest/client.py` | Public prod REST client: markets / orderbook / trades |
| `sources/kalshi_rest/selector.py` | Parse strike from ticker; pick near-money markets vs spot |
| `sources/kalshi_rest/decoder.py` | Tagged raw frame → `list[Event]` (trade + orderbook) |
| `sources/kalshi_rest/poller.py` | Interval poll → tagged raw frames + dedup trades |
| `tests/test_rest_client.py` | Client via MockTransport |
| `tests/test_rest_selector.py` | Strike parse + nearest selection |
| `tests/test_rest_decoder.py` | Trade + orderbook normalization, dollar→cents |

Frame envelope written to disk (one JSON object per frame): `{"kind":"trade"|"orderbook","ticker":<str>,"data":<raw REST object>}`. This lets `decode` dispatch offline.

---

## Task 1: `sources/kalshi_rest/selector.py` (pure functions)

**Files:** Create `sources/kalshi_rest/selector.py`; Test `tests/test_rest_selector.py`.

- [ ] **Step 1: Failing test**
```python
from sources.kalshi_rest.selector import parse_strike, nearest_markets

def test_parse_strike_threshold_and_bucket():
    assert parse_strike("KXBTC-26AUG1917-T73299.99") == 73299.99
    assert parse_strike("KXBTC-26AUG1912-B68550") == 68550.0
    assert parse_strike("KXBTC15M-26AUG191145-45") is None  # no T/B strike suffix
    assert parse_strike("garbage") is None

def test_nearest_markets_sorts_by_distance_to_spot():
    tickers = ["KXBTC-X-B68000", "KXBTC-X-B69000", "KXBTC-X-B68500", "KXBTC-X-T99999.99"]
    out = nearest_markets(tickers, spot=68550.0, n=2)
    assert out == ["KXBTC-X-B68500", "KXBTC-X-B69000"]
```
- [ ] **Step 2: Run → FAIL** (`uv run pytest tests/test_rest_selector.py -v`).
- [ ] **Step 3: Implement**
```python
# sources/kalshi_rest/selector.py
"""Pick near-the-money Kalshi BTC markets from ticker strikes."""
import re

_STRIKE = re.compile(r"-[TB](\d+(?:\.\d+)?)$")


def parse_strike(ticker: str) -> float | None:
    m = _STRIKE.search(ticker)
    return float(m.group(1)) if m else None


def nearest_markets(tickers: list[str], spot: float, n: int) -> list[str]:
    scored = []
    for t in tickers:
        s = parse_strike(t)
        if s is not None:
            scored.append((abs(s - spot), t))
    scored.sort()
    return [t for _, t in scored[:n]]
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add sources/kalshi_rest/selector.py tests/test_rest_selector.py && git commit -m "Add REST market selector"`.

---

## Task 2: `sources/kalshi_rest/decoder.py`

**Files:** Create `sources/kalshi_rest/decoder.py`; Test `tests/test_rest_decoder.py`.

- [ ] **Step 1: Failing test (real trade shape + synthesized book)**
```python
import orjson
from common.event import Kind, Side, Source
from sources.kalshi_rest.decoder import decode

def test_trade_frame_decodes():
    frame = orjson.dumps({"kind": "trade", "ticker": "KXBTC-X-B68550", "data": {
        "trade_id": "abc", "ticker": "KXBTC-X-B68550", "taker_side": "yes",
        "yes_price_dollars": "0.0100", "no_price_dollars": "0.9900",
        "count_fp": "50.00", "created_time": "2026-08-19T15:37:39Z"}})
    events = decode(frame, t_arrival_ns=42)
    assert len(events) == 1
    e = events[0]
    assert e.source == Source.KALSHI_WS or e.source == Source.KALSHI_REST  # see note
    assert e.kind == Kind.TRADE and e.t_arrival_ns == 42
    assert e.market == "KXBTC-X-B68550" and e.price == 1 and e.size == 50 and e.side == Side.YES

def test_trade_no_side_uses_no_price():
    frame = orjson.dumps({"kind": "trade", "ticker": "M", "data": {
        "trade_id": "d", "ticker": "M", "taker_side": "no",
        "yes_price_dollars": "0.3000", "no_price_dollars": "0.7000",
        "count_fp": "3", "created_time": "t"}})
    e = decode(frame, 1)[0]
    assert e.side == Side.NO and e.price == 70

def test_orderbook_frame_expands_per_level():
    frame = orjson.dumps({"kind": "orderbook", "ticker": "M", "data": {
        "yes": [[10, 100], [11, 50]], "no": [[20, 30]]}})
    events = decode(frame, 1)
    assert len(events) == 3
    assert all(e.kind == Kind.BOOK_SNAPSHOT for e in events)
    assert {(e.price, e.size, e.side) for e in events if e.side == Side.YES} == {(10, 100, Side.YES), (11, 50, Side.YES)}

def test_empty_orderbook_yields_nothing():
    frame = orjson.dumps({"kind": "orderbook", "ticker": "M", "data": {"yes": None, "no": None}})
    assert decode(frame, 1) == []
```
> Note: add a `KALSHI_REST` value to `common/event.py`'s `Source` enum (`"kalshi_rest"`) in this task, and use it. Update the test to assert `e.source == Source.KALSHI_REST`.

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** (first add `KALSHI_REST = "kalshi_rest"` to `Source` in `common/event.py`)
```python
# sources/kalshi_rest/decoder.py
"""Decode tagged public-REST frames into normalized Events.
Trade prices are dollar strings (e.g. "0.0100" -> 1 cent); count is a float string."""
import orjson
from common.event import Event, Kind, Side, Source

_SIDE = {"yes": Side.YES, "no": Side.NO}


def _cents(dollar_str: str) -> int:
    return round(float(dollar_str) * 100)


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    frame = orjson.loads(raw)
    kind = frame.get("kind")
    ticker = frame.get("ticker", "")
    data = frame.get("data", {})

    if kind == "trade":
        side = _SIDE.get(data.get("taker_side"))
        price = _cents(data["no_price_dollars"]) if side == Side.NO else _cents(data["yes_price_dollars"])
        return [Event(
            source=Source.KALSHI_REST, t_arrival_ns=t_arrival_ns, market=ticker,
            kind=Kind.TRADE, price=price, size=int(float(data["count_fp"])),
            side=side, seq=None)]

    if kind == "orderbook":
        events: list[Event] = []
        for side_key, side_enum in (("yes", Side.YES), ("no", Side.NO)):
            for level in data.get(side_key) or []:
                events.append(Event(
                    source=Source.KALSHI_REST, t_arrival_ns=t_arrival_ns, market=ticker,
                    kind=Kind.BOOK_SNAPSHOT, price=level[0], size=level[1], side=side_enum, seq=None))
        return events

    return []
```
- [ ] **Step 4: Run → PASS** (update the `test_event.py` nothing needed; the new enum value is additive).
- [ ] **Step 5: Commit** `git add sources/kalshi_rest/decoder.py common/event.py tests/test_rest_decoder.py && git commit -m "Add REST decoder + KALSHI_REST source"`.

---

## Task 3: `sources/kalshi_rest/client.py`

**Files:** Create `sources/kalshi_rest/client.py`; Test `tests/test_rest_client.py` (uses `httpx.MockTransport`, no network).

- [ ] **Step 1: Failing test**
```python
import httpx
from sources.kalshi_rest.client import KalshiRestClient

def _client(handler):
    transport = httpx.MockTransport(handler)
    c = KalshiRestClient()
    c._c = httpx.Client(base_url="https://x/trade-api/v2", transport=transport)
    return c

def test_markets_and_orderbook_and_trades():
    def handler(req):
        if req.url.path.endswith("/markets"):
            return httpx.Response(200, json={"markets": [{"ticker": "M1"}, {"ticker": "M2"}], "cursor": ""})
        if req.url.path.endswith("/orderbook"):
            return httpx.Response(200, json={"orderbook": {"yes": [[10, 5]], "no": None}})
        if req.url.path.endswith("/trades"):
            return httpx.Response(200, json={"trades": [{"trade_id": "t1"}]})
        return httpx.Response(404)
    c = _client(handler)
    assert [m["ticker"] for m in c.markets("KXBTC")] == ["M1", "M2"]
    assert c.orderbook("M1") == {"yes": [[10, 5]], "no": None}
    assert c.trades("M1") == [{"trade_id": "t1"}]
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# sources/kalshi_rest/client.py
"""Thin client for the public Kalshi prod REST (no auth required for reads)."""
import httpx

DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiRestClient:
    def __init__(self, base: str = DEFAULT_BASE, timeout: float = 15.0):
        self._c = httpx.Client(base_url=base, timeout=timeout)

    def markets(self, series_ticker: str, status: str = "open", limit: int = 1000) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            params = {"series_ticker": series_ticker, "status": status, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            d = self._c.get("/markets", params=params).raise_for_status().json()
            out.extend(d.get("markets", []))
            cursor = d.get("cursor")
            if not cursor:
                return out

    def orderbook(self, ticker: str) -> dict:
        d = self._c.get(f"/markets/{ticker}/orderbook").raise_for_status().json()
        return d.get("orderbook", {})

    def trades(self, ticker: str, limit: int = 100) -> list[dict]:
        d = self._c.get("/markets/trades", params={"ticker": ticker, "limit": limit}).raise_for_status().json()
        return d.get("trades", [])

    def close(self) -> None:
        self._c.close()
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add sources/kalshi_rest/client.py tests/test_rest_client.py && git commit -m "Add public Kalshi REST client"`.

---

## Task 4: `sources/kalshi_rest/poller.py` + live smoke

**Files:** Create `sources/kalshi_rest/poller.py`.

- [ ] **Step 1: Implement**
```python
# sources/kalshi_rest/poller.py
"""Poll public Kalshi prod REST for selected markets; write tagged raw frames.
Frame envelope: {"kind":"trade"|"orderbook","ticker":...,"data":...}."""
import argparse
import asyncio
import logging
import time
import orjson
from common.clock import now_ns
from common.storage import FrameWriter
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets

log = logging.getLogger("kalshi_rest.poller")


def _btc_spot() -> float:
    import httpx
    r = httpx.get("https://api.binance.com/api/v3/ticker/price",
                  params={"symbol": "BTCUSDT"}, timeout=10.0)
    return float(r.json()["price"])


async def poll(tickers: list[str], out_path: str, interval_s: float,
               duration_s: float | None) -> None:
    client = KalshiRestClient()
    writer = FrameWriter(out_path)
    seen: set[str] = set()
    deadline = None if duration_s is None else time.monotonic() + duration_s
    try:
        while deadline is None or time.monotonic() < deadline:
            for t in tickers:
                try:
                    ob = client.orderbook(t)
                    writer.write(now_ns(), orjson.dumps({"kind": "orderbook", "ticker": t, "data": ob}))
                    for tr in client.trades(t, limit=50):
                        tid = tr.get("trade_id")
                        if tid and tid not in seen:
                            seen.add(tid)
                            writer.write(now_ns(), orjson.dumps({"kind": "trade", "ticker": t, "data": tr}))
                except Exception as e:  # noqa: BLE001 - keep polling other markets
                    log.warning("poll error for %s: %s", t, e)
            await asyncio.sleep(interval_s)
    finally:
        writer.close()
        client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="KXBTC")
    ap.add_argument("--near", type=int, default=6, help="poll N near-the-money markets")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    client = KalshiRestClient()
    tickers_all = [m["ticker"] for m in client.markets(args.series)]
    client.close()
    tickers = nearest_markets(tickers_all, _btc_spot(), args.near)
    log.info("polling %d markets: %s", len(tickers), tickers)
    dur = args.minutes * 60 if args.minutes else None
    asyncio.run(poll(tickers, args.out, args.interval, dur))


if __name__ == "__main__":
    main()
```
- [ ] **Step 2: Lint** `uv run ruff check sources/kalshi_rest/poller.py` (fix import order only).
- [ ] **Step 3: Live smoke (public prod, ~30s)**
```bash
uv run python -m sources.kalshi_rest.poller --series KXBTC --near 6 --interval 2 --minutes 0.5 --out data/rest_smoke.bin
```
Expected: logs the near-money markets; exits after ~30s; `data/rest_smoke.bin` has frames. Verify + decode:
```bash
uv run python -c "
from common.storage import read_frames
from sources.kalshi_rest.decoder import decode
from common.event import Kind
m=t=b=0
for ts,p in read_frames('data/rest_smoke.bin'):
    m+=1
    for e in decode(p,ts):
        if e.kind==Kind.TRADE: t+=1
        else: b+=1
print(f'{m} frames -> {t} trade events, {b} book-level events')
"
```
Report the counts. (Trades appear if any BTC trade prints during the window; book events appear only if depth is present. Either way frames>0 proves the pipeline.)
- [ ] **Step 4: Commit** `git add sources/kalshi_rest/poller.py && git commit -m "Add public REST poller + live smoke"`.

---

## Task 5: Full suite + lint + docs

- [ ] **Step 1:** `uv run pytest -q` (all green) and `uv run ruff check .` (clean).
- [ ] **Step 2:** Append to `docs/feed-notes.md` a "REST shapes (observed prod)" section with the real trade JSON and the note that public REST orderbook depth is typically empty.
- [ ] **Step 3:** Append a dated line to `docs/log.md` (REST adapter added; smoke counts).
- [ ] **Step 4: Commit** `git add docs/feed-notes.md docs/log.md && git commit -m "Document REST shapes + log"`.

## Definition of Done
- `pytest` + `ruff` green; new adapter behind the same `Event` contract.
- Live smoke: poller runs against public prod, writes frames, decoder produces trade events (and book events when depth exists), no key used.
- `Source.KALSHI_REST` added; design §12 reflected in code.
