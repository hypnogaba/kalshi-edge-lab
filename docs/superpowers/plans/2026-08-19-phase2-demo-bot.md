# Phase 2 — Keyless Trade-Signal Demo Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** A deliberately simple bot that watches real Kalshi BTC trades (public REST, keyless) + Binance BTC spot, forms a naive directional signal, places **Kalshi DEMO** orders through the v2 order API, enforces hard guardrails, logs every decision, and shows a live dashboard.

**Architecture:** Reuses the source adapters. `reference/binance_ws.py` streams spot. `bot/signal.py` is a pure function. `bot/order_manager.py` talks to the Kalshi **demo** v2 REST. `bot/guardrails.py` enforces ceilings independent of config. `bot/run.py` wires poll→signal→guardrails→order→log. `dash/tui.py` renders state.

**Tech Stack:** Python 3.12, httpx, websockets, orjson, rich, existing `common/` + `sources/`.

**Ground rules:** DEMO only (order manager base URL is the demo API; no prod trading endpoints). Hard ceilings independent of config + kill-switch file checked each loop. Every published number reproducible. No profit claims — the signal is an openly labeled dumb example.

**Known external state:** the demo account currently has $0 balance, so live order placement will be rejected until the user funds the demo account. All code is built + unit-tested without funds; the live order smoke (Task 7) is gated on funding.

**Signal scope (v0):** target **threshold** BTC markets (ticker suffix `-T<strike>`, i.e. "BTC ≥ strike?"). Bucket markets (`-B<strike>`) → HOLD for now.

---

## File Structure

| File | Responsibility |
|---|---|
| `reference/__init__.py`, `reference/binance_ws.py` | Stream Binance BTCUSDT spot mid; expose latest |
| `bot/__init__.py` | package |
| `bot/signal.py` | Pure: (strike, is_threshold, kalshi_yes_cents, spot, cfg) → Decision |
| `bot/guardrails.py` | Hard ceilings + rate limit + kill-switch file |
| `bot/order_manager.py` | Kalshi DEMO v2 REST: place / cancel / positions |
| `bot/decision_log.py` | Append-only JSONL decision log |
| `bot/config.py` | Bot tunables (env/dataclass) |
| `bot/run.py` | Main loop wiring |
| `dash/__init__.py`, `dash/tui.py` | Rich dashboard |
| `tests/test_signal.py`, `test_guardrails.py`, `test_order_manager.py`, `test_decision_log.py`, `test_binance_ref.py` | unit tests |

---

## Task 1: `bot/signal.py` (pure)

**Files:** Create `bot/__init__.py`, `bot/signal.py`; Test `tests/test_signal.py`.

- [ ] **Step 1: Failing test**
```python
from bot.signal import decide, Decision, SignalConfig

CFG = SignalConfig(entry_dollars=50.0, max_yes_cents=90, min_yes_cents=10)

def test_hold_on_bucket_market():
    assert decide(strike=68000, is_threshold=False, kalshi_yes_cents=50, spot=69000, cfg=CFG) == Decision.HOLD

def test_buy_yes_when_spot_well_above_strike_and_not_priced_in():
    # spot far above strike -> "yes" likely; market yes price still cheap -> underpriced -> BUY_YES
    assert decide(strike=68000, is_threshold=True, kalshi_yes_cents=60, spot=69000, cfg=CFG) == Decision.BUY_YES

def test_hold_when_already_priced_in():
    # spot above strike but market already near-certain (yes >= max) -> no edge
    assert decide(strike=68000, is_threshold=True, kalshi_yes_cents=95, spot=69000, cfg=CFG) == Decision.HOLD

def test_buy_no_when_spot_well_below_strike_and_yes_still_expensive():
    assert decide(strike=70000, is_threshold=True, kalshi_yes_cents=40, spot=69000, cfg=CFG) == Decision.BUY_NO

def test_hold_inside_entry_band():
    # spot within entry_dollars of strike -> too close to call -> HOLD
    assert decide(strike=69000, is_threshold=True, kalshi_yes_cents=50, spot=69010, cfg=CFG) == Decision.HOLD
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# bot/signal.py
"""Naive v0 signal for threshold BTC markets. Explicitly a dumb example — no edge claims.
Idea: if Binance spot is clearly above the strike, "YES" (BTC >= strike) is likely; if the
Kalshi YES price hasn't caught up (still cheap), lean BUY_YES. Symmetric for below-strike."""
from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    BUY_YES = "buy_yes"   # side=bid
    BUY_NO = "buy_no"     # side=ask
    HOLD = "hold"


@dataclass(frozen=True)
class SignalConfig:
    entry_dollars: float   # spot must be beyond strike by at least this many $ to act
    max_yes_cents: int     # above this, "yes" is already priced in -> no edge
    min_yes_cents: int     # below this, "no" is already priced in -> no edge


def decide(strike: float, is_threshold: bool, kalshi_yes_cents: int,
           spot: float, cfg: SignalConfig) -> Decision:
    if not is_threshold:
        return Decision.HOLD
    dist = spot - strike
    if abs(dist) < cfg.entry_dollars:
        return Decision.HOLD
    if dist > 0 and kalshi_yes_cents < cfg.max_yes_cents:
        return Decision.BUY_YES
    if dist < 0 and kalshi_yes_cents > cfg.min_yes_cents:
        return Decision.BUY_NO
    return Decision.HOLD
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add bot/__init__.py bot/signal.py tests/test_signal.py && git commit -m "Add naive v0 trade signal"`.

---

## Task 2: `bot/guardrails.py`

**Files:** Create `bot/guardrails.py`; Test `tests/test_guardrails.py`.

- [ ] **Step 1: Failing test**
```python
from bot.guardrails import Guardrails, GuardrailBreach
import pytest

def test_position_ceiling(tmp_path):
    g = Guardrails(max_position=5, max_orders_per_min=100, max_daily_loss_cents=10_000,
                   kill_switch_path=str(tmp_path / "kill"))
    g.check(current_position=4, add_count=1, daily_pnl_cents=0, now_s=0.0)  # ok (=5)
    with pytest.raises(GuardrailBreach):
        g.check(current_position=5, add_count=1, daily_pnl_cents=0, now_s=0.0)  # exceeds

def test_daily_loss_ceiling(tmp_path):
    g = Guardrails(5, 100, 10_000, str(tmp_path / "kill"))
    with pytest.raises(GuardrailBreach):
        g.check(current_position=0, add_count=1, daily_pnl_cents=-10_001, now_s=0.0)

def test_rate_limit(tmp_path):
    g = Guardrails(100, 2, 10_000, str(tmp_path / "kill"))
    g.check(0, 1, 0, now_s=0.0)
    g.check(0, 1, 0, now_s=1.0)
    with pytest.raises(GuardrailBreach):
        g.check(0, 1, 0, now_s=2.0)  # 3rd within 60s window

def test_kill_switch(tmp_path):
    p = tmp_path / "kill"
    p.write_text("stop")
    g = Guardrails(100, 100, 10_000, str(p))
    with pytest.raises(GuardrailBreach):
        g.check(0, 1, 0, now_s=0.0)
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# bot/guardrails.py
"""Hard safety ceilings, independent of strategy config. Raise GuardrailBreach to block an order."""
import os
from collections import deque


class GuardrailBreach(Exception):
    pass


class Guardrails:
    def __init__(self, max_position: int, max_orders_per_min: int,
                 max_daily_loss_cents: int, kill_switch_path: str):
        self.max_position = max_position
        self.max_orders_per_min = max_orders_per_min
        self.max_daily_loss_cents = max_daily_loss_cents
        self.kill_switch_path = kill_switch_path
        self._order_times: deque[float] = deque()

    def check(self, current_position: int, add_count: int,
              daily_pnl_cents: int, now_s: float) -> None:
        if os.path.exists(self.kill_switch_path):
            raise GuardrailBreach("kill switch engaged")
        if abs(current_position) + add_count > self.max_position:
            raise GuardrailBreach(f"position ceiling {self.max_position}")
        if daily_pnl_cents <= -self.max_daily_loss_cents:
            raise GuardrailBreach(f"daily loss ceiling {self.max_daily_loss_cents}c")
        while self._order_times and now_s - self._order_times[0] >= 60.0:
            self._order_times.popleft()
        if len(self._order_times) + 1 > self.max_orders_per_min:
            raise GuardrailBreach(f"rate limit {self.max_orders_per_min}/min")
        self._order_times.append(now_s)
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add bot/guardrails.py tests/test_guardrails.py && git commit -m "Add hard guardrails + kill switch"`.

---

## Task 3: `bot/decision_log.py`

**Files:** Create `bot/decision_log.py`; Test `tests/test_decision_log.py`.

- [ ] **Step 1: Failing test**
```python
import orjson
from bot.decision_log import DecisionLog

def test_append_and_readback(tmp_path):
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(str(p))
    log.record(t_ns=1, market="M", kalshi_yes_cents=50, spot=69000.0,
               signal="buy_yes", action="placed", result={"order_id": "x"})
    log.close()
    lines = p.read_text().splitlines()
    assert len(lines) == 1
    row = orjson.loads(lines[0])
    assert row["market"] == "M" and row["signal"] == "buy_yes" and row["result"]["order_id"] == "x"
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# bot/decision_log.py
"""Append-only JSONL decision log — every decision the bot makes. This log is later content."""
import orjson


class DecisionLog:
    def __init__(self, path: str):
        self._f = open(path, "ab", buffering=0)

    def record(self, t_ns: int, market: str, kalshi_yes_cents: int | None,
               spot: float | None, signal: str, action: str, result: dict | None) -> None:
        row = {"t_ns": t_ns, "market": market, "kalshi_yes_cents": kalshi_yes_cents,
               "spot": spot, "signal": signal, "action": action, "result": result}
        self._f.write(orjson.dumps(row) + b"\n")

    def close(self) -> None:
        self._f.close()
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add bot/decision_log.py tests/test_decision_log.py && git commit -m "Add append-only decision log"`.

---

## Task 4: `bot/order_manager.py` (Kalshi DEMO v2 REST)

**Files:** Create `bot/order_manager.py`; Test `tests/test_order_manager.py` (MockTransport; no network, no funds needed).

v2 order API (verified): `POST /trade-api/v2/portfolio/events/orders`, body `{ticker, client_order_id, side:"bid"(buy YES)|"ask"(buy NO), count:"<fixed-point>", price:"<dollars fixed-point>", time_in_force, self_trade_prevention_type}`. Cancel: `DELETE /trade-api/v2/portfolio/events/orders/{order_id}`. Positions: `GET /trade-api/v2/portfolio/positions`. All signed with the DEMO key (path without query). Price cents→dollars string: `f"{cents/100:.4f}"`; count→`f"{n:.2f}"`.

- [ ] **Step 1: Failing test**
```python
import httpx, orjson
from bot.order_manager import OrderManager

def _om(handler):
    om = OrderManager(key_id="k", private_key_path="unused", base="https://d/trade-api/v2")
    om._signer = _FakeSigner()
    om._c = httpx.Client(base_url="https://d/trade-api/v2", transport=httpx.MockTransport(handler))
    return om

class _FakeSigner:
    key_id = "k"
    def headers(self, method, path, now_ms=None):
        return {"KALSHI-ACCESS-KEY": "k", "KALSHI-ACCESS-SIGNATURE": "s", "KALSHI-ACCESS-TIMESTAMP": "1"}

def test_place_buy_yes_builds_v2_body():
    captured = {}
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/portfolio/events/orders"):
            captured.update(orjson.loads(req.content))
            return httpx.Response(201, json={"order": {"order_id": "o1"}})
        return httpx.Response(404)
    om = _om(handler)
    oid = om.place(ticker="KXBTCD-X-T68000", buy_yes=True, count=2, price_cents=56, coid="c1")
    assert oid == "o1"
    assert captured["ticker"] == "KXBTCD-X-T68000"
    assert captured["side"] == "bid"
    assert captured["count"] == "2.00"
    assert captured["price"] == "0.5600"
    assert captured["client_order_id"] == "c1"
    assert captured["time_in_force"] == "good_till_canceled"

def test_place_buy_no_uses_ask():
    def handler(req):
        return httpx.Response(201, json={"order": {"order_id": "o2"}})
    om = _om(handler)
    assert om.place("M", buy_yes=False, count=1, price_cents=30, coid="c2") == "o2"

def test_cancel_hits_delete_path():
    seen = {}
    def handler(req):
        seen["method"] = req.method; seen["path"] = req.url.path
        return httpx.Response(200, json={})
    om = _om(handler)
    om.cancel("o1")
    assert seen["method"] == "DELETE" and seen["path"].endswith("/portfolio/events/orders/o1")
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# bot/order_manager.py
"""Kalshi DEMO order manager (v2 REST). DEMO ONLY — base URL is the demo API.
side bid = buy YES, ask = buy NO. price/count are fixed-point strings."""
import httpx
from sources.kalshi_ws.auth import KalshiSigner

_ORDERS = "/trade-api/v2/portfolio/events/orders"
_POSITIONS = "/trade-api/v2/portfolio/positions"


class OrderManager:
    def __init__(self, key_id: str, private_key_path: str, base: str):
        self._signer = KalshiSigner(key_id, private_key_path)
        self._base = base.replace("/trade-api/v2", "")
        self._c = httpx.Client(base_url=self._base, timeout=15.0)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        h = self._signer.headers(method, path)
        h["Content-Type"] = "application/json"
        return h

    def place(self, ticker: str, buy_yes: bool, count: int, price_cents: int, coid: str) -> str:
        body = {
            "ticker": ticker,
            "client_order_id": coid,
            "side": "bid" if buy_yes else "ask",
            "count": f"{count:.2f}",
            "price": f"{price_cents / 100:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
        }
        r = self._c.post(_ORDERS, headers=self._headers("POST", _ORDERS), json=body)
        r.raise_for_status()
        return r.json().get("order", {}).get("order_id")

    def cancel(self, order_id: str) -> None:
        path = f"{_ORDERS}/{order_id}"
        self._c.delete(path, headers=self._headers("DELETE", path)).raise_for_status()

    def positions(self) -> list[dict]:
        r = self._c.get(_POSITIONS, headers=self._headers("GET", _POSITIONS))
        r.raise_for_status()
        return r.json().get("market_positions", [])

    def close(self) -> None:
        self._c.close()
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add bot/order_manager.py tests/test_order_manager.py && git commit -m "Add Kalshi demo v2 order manager"`.

---

## Task 5: `reference/binance_ws.py`

**Files:** Create `reference/__init__.py`, `reference/binance_ws.py`; Test `tests/test_binance_ref.py`.

A small async client over `common.ws_client.ReconnectingWS` that tracks the latest Binance BTCUSDT bookTicker mid. `bookTicker` messages look like `{"u":..,"s":"BTCUSDT","b":"<bid>","B":..,"a":"<ask>","A":..}`. Mid = (float(b)+float(a))/2.

- [ ] **Step 1: Failing test** (unit-test the message parser purely)
```python
from reference.binance_ws import parse_mid

def test_parse_mid():
    assert parse_mid('{"u":1,"s":"BTCUSDT","b":"68000.0","B":"1","a":"68002.0","A":"2"}') == 68001.0

def test_parse_mid_ignores_non_ticker():
    assert parse_mid('{"result":null,"id":1}') is None
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# reference/binance_ws.py
"""Binance BTCUSDT bookTicker → latest mid. Single external reference source."""
import asyncio
import orjson
from common.ws_client import ReconnectingWS

WS_URL = "wss://fstream.binance.com/ws/btcusdt@bookTicker"


def parse_mid(raw: str | bytes) -> float | None:
    msg = orjson.loads(raw)
    if "b" in msg and "a" in msg:
        return (float(msg["b"]) + float(msg["a"])) / 2
    return None


class BinanceRef:
    def __init__(self, url: str = WS_URL):
        self.mid: float | None = None
        self._client = ReconnectingWS(url, dict, self._on_message)

    async def _on_message(self, raw: str | bytes) -> None:
        m = parse_mid(raw)
        if m is not None:
            self.mid = m

    async def run(self) -> None:
        await self._client.run()

    def stop(self) -> None:
        self._client.stop()
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add reference/__init__.py reference/binance_ws.py tests/test_binance_ref.py && git commit -m "Add Binance spot reference"`.

---

## Task 6: `bot/config.py` + `bot/run.py` (wiring)

**Files:** Create `bot/config.py`, `bot/run.py`.

`bot/config.py`: a dataclass of tunables with env overrides — `series` (default `KXBTCD`), `near` (markets to watch), `poll_interval_s`, `SignalConfig` params, guardrail ceilings, `order_count`, `order_price_cents`, `kill_switch_path`, `decision_log_path`. No secrets.

`bot/run.py`: main loop (no unit test; validated live in Task 7):
1. Start `BinanceRef` in a background task.
2. Pick near-money **threshold** markets via `sources.kalshi_rest.selector.nearest_markets` filtered to `-T` tickers.
3. Each interval: for each market, get latest trade (via `KalshiRestClient.trades(ticker, limit=1)`) → `kalshi_yes_cents` (from `yes_price_dollars`), read `BinanceRef.mid`, call `signal.decide(...)`.
4. On BUY_YES/BUY_NO: `guardrails.check(...)`; if ok, `order_manager.place(...)` (DEMO); record to `decision_log`. On `GuardrailBreach` or HOLD: record with the reason, no order.
5. Handle `--minutes` timed shutdown and SIGINT; close writers.

- [ ] **Step 1:** Implement `bot/config.py` (dataclass + `from_env()`), then `bot/run.py` per the above. Ensure `uv run ruff check bot/` is clean and `uv run python -c "import bot.run"` imports without error.
- [ ] **Step 2: Commit** `git add bot/config.py bot/run.py && git commit -m "Add bot config + main loop wiring"`.

---

## Task 7: `dash/tui.py` + live dry-run

**Files:** Create `dash/__init__.py`, `dash/tui.py`.

`dash/tui.py`: a `rich`-based renderer that, given the current state (latest spot, per-market kalshi yes price + signal, position, paper PnL, last N decisions), draws a dark, screenshot-friendly panel. Provide a `render(state: dict) -> rich.console.RenderableType` pure-ish function and a `tail(decision_log_path)` mode that reads the JSONL and displays the latest rows (so it works even before live trading).

- [ ] **Step 1:** Implement `dash/tui.py` with a `render(state)` function and a `main()` that tails the decision log. `uv run ruff check dash/` clean; `uv run python -c "import dash.tui"` imports.
- [ ] **Step 2:** Full suite `uv run pytest -q` (all green) + `uv run ruff check .` (clean).
- [ ] **Step 3: DRY-RUN live (no funds needed):** run the bot in **signal-only** mode — set the kill-switch file so `guardrails.check` blocks every order, so `run.py` computes real signals from real prod trades + Binance but places NO orders, recording HOLD/blocked decisions:
```bash
touch data/KILL
uv run python -m bot.run --minutes 1 --kill-switch data/KILL --decision-log data/decisions.jsonl
uv run python -c "print(open('data/decisions.jsonl').read()[:800])"
```
Expected: decisions recorded with real spot + kalshi prices; zero orders placed (kill switch). Report a sample.
- [ ] **Step 4: LIVE ORDER SMOKE — gated on demo funding.** Only once the demo account has balance: remove the kill switch, run `--minutes 1` against one near-money threshold market with `order_count=1` and a far-from-mid `order_price_cents` (won't fill), confirm an order id comes back and is then cancelled, and that `docs/log.md` records it. If balance is still $0, SKIP this step and note it.
- [ ] **Step 5: Commit** `git add dash bot data/.gitkeep 2>/dev/null; git add dash/__init__.py dash/tui.py && git commit -m "Add dashboard + live dry-run"`. (Do not commit anything under data/.)

---

## Definition of Done
- `pytest` + `ruff` green. Signal, guardrails, decision log, order-manager request-building, and Binance parser all unit-tested.
- Dry-run: real signals computed from real prod trades + Binance, decisions logged, zero orders (kill switch) — proves the full loop without funds.
- Live order smoke passes once demo is funded (else explicitly skipped/noted).
- DEMO-only guaranteed: order manager base is the demo API; hard ceilings + kill switch enforced every loop.

**Deferred (needs prod WS key):** order-book mid signal + the Latency Race (Phase 1). This bot swaps to those via the same `Event`/signal seams with no rewrite.
