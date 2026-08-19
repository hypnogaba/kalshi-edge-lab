# Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the repo, the source-agnostic core, and a working Kalshi public-WS capture + decoder that normalizes live BTC market data into `Event` objects, all covered by tests.

**Architecture:** Source-adapter pattern. Each source = a capture daemon (raw bytes → append-only disk) + a decoder (raw → normalized `Event`). Phase 0 delivers the shared core (`common/`) and the first real adapter (`sources/kalshi_ws/`). The DoubleZero feed adapter is stubbed behind the same interface for a later phase. Everything downstream only ever consumes `Event` streams.

**Tech Stack:** Python 3.12, `uv`, `ruff`, `pytest` + `pytest-asyncio`. Libraries: `websockets` (async WS), `cryptography` (RSA-PSS signing), `orjson` (fast JSON), `httpx` (REST smoke test), `python-dotenv` (config), `uvloop` (event loop).

**Ground rules baked in:** one monotonic clock (`CLOCK_MONOTONIC_RAW`) for all arrival timestamps; never compare timestamps across machines; never commit secrets (`.env` + `secrets/` already gitignored); demo/read-only endpoints only.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata, deps, ruff/pytest config |
| `Makefile` | `setup`, `test`, `lint`, `check-auth`, `discover`, `capture` targets |
| `common/clock.py` | Single monotonic arrival clock (`now_ns`) |
| `common/event.py` | Normalized `Event` + `Source`/`Kind`/`Side` enums |
| `common/storage.py` | Append-only frame writer/reader `(t_arrival_ns, bytes)` |
| `common/config.py` | Load `.env`, typed Kalshi config accessors |
| `common/ws_client.py` | Reconnecting async WS client with backoff |
| `sources/kalshi_ws/auth.py` | Kalshi RSA-PSS request signer |
| `sources/kalshi_ws/capture.py` | Join Kalshi WS, subscribe, write raw frames |
| `sources/kalshi_ws/decoder.py` | Decode raw Kalshi JSON → `list[Event]` |
| `sources/dz_feed/capture.py` | Stub (multicast join) — raises with pointer to README |
| `sources/dz_feed/decoder.py` | Stub (wire-format decode) — raises with pointer to README |
| `sources/dz_feed/README.md` | Exactly what is needed from Ivan to implement |
| `scripts/check_auth.py` | Live smoke test: signed GET against demo REST |
| `scripts/discover_markets.py` | List Kalshi BTC markets → find real ticker |
| `scripts/dump_message_types.py` | Summarize distinct message shapes from a capture |
| `scripts/verify_capture.py` | Phase 0 acceptance checks over a capture file |
| `docs/env.md` | Environment audit + tradebot reuse decisions |
| `docs/feed-notes.md` | Real captured Kalshi message shapes |
| `tests/…` | Unit tests mirroring the modules above |

---

## Task 0: Project scaffold and tooling

**Files:**
- Create: `pyproject.toml`, `Makefile`, `README.md`
- Create: `common/__init__.py`, `sources/__init__.py`, `sources/kalshi_ws/__init__.py`, `sources/dz_feed/__init__.py`, `scripts/__init__.py`, `tests/__init__.py`
- Create: `docs/env.md`, `docs/feed-notes.md`, `docs/log.md` (empty stubs)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "kalshi-edge-lab"
version = "0.0.1"
description = "Kalshi x DoubleZero Edge Lab — latency race + demo trading bot"
requires-python = ">=3.12"
dependencies = [
    "websockets>=13.0",
    "cryptography>=43.0",
    "orjson>=3.10",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "uvloop>=0.20; sys_platform != 'win32'",
]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.6"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["common", "sources"]
```

- [ ] **Step 2: Write `Makefile`**

```makefile
.PHONY: setup test lint check-auth discover capture
setup:
	uv sync
test:
	uv run pytest -q
lint:
	uv run ruff check .
check-auth:
	uv run python -m scripts.check_auth
discover:
	uv run python -m scripts.discover_markets
capture:
	uv run python -m sources.kalshi_ws.capture --market $(MARKET) --minutes $(MINUTES) --out $(OUT)
```

- [ ] **Step 3: Create package dirs with empty `__init__.py` and empty doc stubs**

Run:
```bash
mkdir -p common sources/kalshi_ws sources/dz_feed scripts tests data
touch common/__init__.py sources/__init__.py sources/kalshi_ws/__init__.py \
      sources/dz_feed/__init__.py scripts/__init__.py tests/__init__.py
printf '# Environment audit\n\n(fill during Task 13)\n' > docs/env.md
printf '# Kalshi feed notes\n\n(fill during Task 10)\n' > docs/feed-notes.md
printf '# Session log\n' > docs/log.md
```

- [ ] **Step 4: Write minimal `README.md`**

```markdown
# Kalshi Edge Lab
Latency race + demo trading bot for the Kalshi x DoubleZero Edge Lab. See `SPEC.md` and `docs/superpowers/specs/` for the design. Setup: `make setup`. Tests: `make test`.
```

- [ ] **Step 5: Sync and verify tooling**

Run: `make setup && make lint`
Expected: dependencies install; ruff reports no errors (or only auto-fixable ones).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml Makefile README.md common sources scripts tests docs
git commit -m "Scaffold project: tooling, package layout, doc stubs"
```

---

## Task 1: `common/clock.py` — single monotonic clock

**Files:**
- Create: `common/clock.py`
- Test: `tests/test_clock.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clock.py
from common.clock import now_ns

def test_now_ns_is_int_and_nondecreasing():
    a = now_ns()
    b = now_ns()
    assert isinstance(a, int)
    assert b >= a
    assert a > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: common.clock`.

- [ ] **Step 3: Write minimal implementation**

```python
# common/clock.py
"""Single monotonic arrival clock. CLOCK_MONOTONIC_RAW on Linux (the DZ server);
falls back to monotonic_ns on platforms without RAW (e.g. macOS dev)."""
import time


def now_ns() -> int:
    raw = getattr(time, "CLOCK_MONOTONIC_RAW", None)
    if raw is not None:
        try:
            return time.clock_gettime_ns(raw)
        except OSError:
            pass
    return time.monotonic_ns()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_clock.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/clock.py tests/test_clock.py
git commit -m "Add monotonic arrival clock"
```

---

## Task 2: `common/event.py` — normalized event

**Files:**
- Create: `common/event.py`
- Test: `tests/test_event.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event.py
from common.event import Event, Source, Kind, Side

def test_event_construction_and_immutability():
    e = Event(source=Source.KALSHI_WS, t_arrival_ns=123, market="BTC",
              kind=Kind.TRADE, price=52, size=10, side=Side.YES, seq=7)
    assert e.source == "kalshi_ws"
    assert e.kind == "trade"
    assert e.price == 52 and e.size == 10 and e.side == "yes" and e.seq == 7
    try:
        e.price = 99  # frozen
        assert False, "Event should be immutable"
    except AttributeError:
        pass

def test_event_optional_fields_default_none():
    e = Event(source=Source.DZ_FEED, t_arrival_ns=1, market="BTC", kind=Kind.BOOK_SNAPSHOT)
    assert e.price is None and e.size is None and e.side is None and e.seq is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_event.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# common/event.py
"""Normalized market event. All sources decode to this type."""
from dataclasses import dataclass
from enum import Enum


class Source(str, Enum):
    KALSHI_WS = "kalshi_ws"
    DZ_FEED = "dz_feed"


class Kind(str, Enum):
    TRADE = "trade"
    BOOK_DELTA = "book_delta"
    BOOK_SNAPSHOT = "book_snapshot"


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass(frozen=True, slots=True)
class Event:
    source: Source
    t_arrival_ns: int
    market: str
    kind: Kind
    price: int | None = None   # price level, cents
    size: int | None = None    # contracts; for deltas this is the signed change
    side: Side | None = None
    seq: int | None = None      # sequence number or message id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_event.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/event.py tests/test_event.py
git commit -m "Add normalized Event type"
```

---

## Task 3: `common/storage.py` — append-only frame log

**Files:**
- Create: `common/storage.py`
- Test: `tests/test_storage.py`

Frame format on disk: little-endian `u64 t_arrival_ns`, `u32 payload_len`, then `payload_len` raw bytes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py
from common.storage import FrameWriter, read_frames

def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "cap.bin"
    with FrameWriter(p) as w:
        w.write(1000, b"hello")
        w.write(2000, b"world!!")
    frames = list(read_frames(p))
    assert frames == [(1000, b"hello"), (2000, b"world!!")]

def test_truncated_tail_is_ignored(tmp_path):
    p = tmp_path / "cap.bin"
    with FrameWriter(p) as w:
        w.write(1, b"ok")
    with open(p, "ab") as f:
        f.write(b"\x05\x00")  # partial header, must not crash the reader
    assert list(read_frames(p)) == [(1, b"ok")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# common/storage.py
"""Append-only binary frame log: (t_arrival_ns:u64, len:u32, payload)."""
import struct
from pathlib import Path
from collections.abc import Iterator

_HEADER = struct.Struct("<QI")


class FrameWriter:
    def __init__(self, path: str | Path):
        self._f = open(path, "ab", buffering=0)

    def write(self, t_arrival_ns: int, payload: bytes) -> None:
        self._f.write(_HEADER.pack(t_arrival_ns, len(payload)))
        self._f.write(payload)

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> "FrameWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_frames(path: str | Path) -> Iterator[tuple[int, bytes]]:
    with open(path, "rb") as f:
        while True:
            header = f.read(_HEADER.size)
            if len(header) < _HEADER.size:
                return
            t, n = _HEADER.unpack(header)
            payload = f.read(n)
            if len(payload) < n:
                return  # truncated tail from an interrupted write
            yield t, payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/storage.py tests/test_storage.py
git commit -m "Add append-only frame storage"
```

---

## Task 4: `common/config.py` — env + typed Kalshi config

**Files:**
- Create: `common/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from common.config import kalshi_demo, get

def test_get_required_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_VAR", raising=False)
    with pytest.raises(RuntimeError):
        get("SOME_VAR", required=True)

def test_kalshi_demo_reads_env(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_KEY_ID", "kid")
    monkeypatch.setenv("KALSHI_DEMO_PRIVATE_KEY_PATH", "secrets/x.pem")
    monkeypatch.setenv("KALSHI_DEMO_WS", "wss://demo/ws")
    monkeypatch.setenv("KALSHI_DEMO_API_BASE", "https://demo/api")
    cfg = kalshi_demo()
    assert cfg.key_id == "kid"
    assert cfg.private_key_path == "secrets/x.pem"
    assert cfg.ws_url == "wss://demo/ws"
    assert cfg.api_base == "https://demo/api"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# common/config.py
"""Environment/config loading. Loads .env once; typed accessors for Kalshi."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()  # loads .env from cwd if present; no-op otherwise


def get(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class KalshiConfig:
    key_id: str
    private_key_path: str
    ws_url: str
    api_base: str | None = None


def kalshi_demo() -> KalshiConfig:
    return KalshiConfig(
        key_id=get("KALSHI_DEMO_KEY_ID", required=True),
        private_key_path=get("KALSHI_DEMO_PRIVATE_KEY_PATH", required=True),
        ws_url=get("KALSHI_DEMO_WS", required=True),
        api_base=get("KALSHI_DEMO_API_BASE"),
    )


def kalshi_prod() -> KalshiConfig:
    return KalshiConfig(
        key_id=get("KALSHI_PROD_KEY_ID", required=True),
        private_key_path=get("KALSHI_PROD_PRIVATE_KEY_PATH", required=True),
        ws_url=get("KALSHI_PROD_WS", required=True),
        api_base=get("KALSHI_PROD_API_BASE"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/config.py tests/test_config.py
git commit -m "Add env config loader"
```

---

## Task 5: `sources/kalshi_ws/auth.py` — RSA-PSS signer

**Files:**
- Create: `sources/kalshi_ws/auth.py`
- Test: `tests/test_auth.py`

Sign message = `timestamp_ms + METHOD + path` with RSA-PSS (MGF1-SHA256, salt = digest length), SHA256, base64-encoded. PSS is randomized, so the test **verifies** the signature with the public key rather than comparing bytes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from sources.kalshi_ws.auth import KalshiSigner

def _make_key(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption())
    p = tmp_path / "k.pem"
    p.write_bytes(pem)
    return p, key.public_key()

def test_signature_verifies(tmp_path):
    path, pub = _make_key(tmp_path)
    signer = KalshiSigner("kid-123", str(path))
    sig_b64 = signer.sign("1700000000000", "GET", "/trade-api/ws/v2")
    msg = ("1700000000000" + "GET" + "/trade-api/ws/v2").encode()
    pub.verify(
        base64.b64decode(sig_b64), msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256())  # raises InvalidSignature if wrong

def test_headers_shape(tmp_path):
    path, _ = _make_key(tmp_path)
    signer = KalshiSigner("kid-123", str(path))
    h = signer.headers("GET", "/trade-api/ws/v2", now_ms=1700000000000)
    assert h["KALSHI-ACCESS-KEY"] == "kid-123"
    assert h["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    assert isinstance(h["KALSHI-ACCESS-SIGNATURE"], str) and h["KALSHI-ACCESS-SIGNATURE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# sources/kalshi_ws/auth.py
"""Kalshi RSA-PSS request signer. See docs.kalshi.com/getting_started/api_keys."""
import base64
import time
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiSigner:
    def __init__(self, key_id: str, private_key_path: str):
        self.key_id = key_id
        self._key = serialization.load_pem_private_key(
            Path(private_key_path).read_bytes(), password=None)

    def sign(self, timestamp_ms: str, method: str, path: str) -> str:
        msg = (timestamp_ms + method + path).encode()
        sig = self._key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=hashes.SHA256().digest_size),
            hashes.SHA256())
        return base64.b64encode(sig).decode()

    def headers(self, method: str, path: str, now_ms: int | None = None) -> dict[str, str]:
        ts = str(now_ms if now_ms is not None else int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": self.sign(ts, method, path),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add sources/kalshi_ws/auth.py tests/test_auth.py
git commit -m "Add Kalshi RSA-PSS signer"
```

---

## Task 6: `scripts/check_auth.py` — live credential smoke test

**Files:**
- Create: `scripts/check_auth.py`

This is a **live** check against the demo REST API. It proves the demo Key ID + private key authenticate end-to-end. Signed path is the full request path without query string.

- [ ] **Step 1: Write the script**

```python
# scripts/check_auth.py
"""Live smoke test: signed GET /portfolio/balance against Kalshi demo REST.
Run: uv run python -m scripts.check_auth"""
import sys
import httpx
from common.config import kalshi_demo
from sources.kalshi_ws.auth import KalshiSigner

PATH = "/trade-api/v2/portfolio/balance"


def main() -> int:
    cfg = kalshi_demo()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    base = cfg.api_base.replace("/trade-api/v2", "")  # host root
    headers = signer.headers("GET", PATH)
    r = httpx.get(base + PATH, headers=headers, timeout=10.0)
    print(f"HTTP {r.status_code}")
    print(r.text[:500])
    if r.status_code == 200:
        print("AUTH OK — demo credentials work.")
        return 0
    print("AUTH FAILED — check KALSHI_DEMO_KEY_ID / private key / clock skew.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the live smoke test**

Run: `make check-auth`
Expected: `HTTP 200` and `AUTH OK — demo credentials work.`
If `HTTP 401`: re-check the Key ID, that the private key matches, and that the system clock is not skewed (timestamp is in ms).

- [ ] **Step 3: Record the result in `docs/log.md`**

Append a line: date, `check-auth` result, and the balance response summary. Do **not** paste keys.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_auth.py docs/log.md
git commit -m "Add live demo-credential smoke test"
```

---

## Task 7: `common/ws_client.py` — reconnecting WS client

**Files:**
- Create: `common/ws_client.py`
- Test: `tests/test_ws_client.py`

Async client: connects with per-connection handshake headers (from a factory, so each reconnect re-signs), sends subscribe messages on connect, forwards every inbound message to an async `on_message`, and reconnects with exponential backoff. `websockets>=13` uses `additional_headers`.

- [ ] **Step 1: Write the failing test (uses a local mock WS server)**

```python
# tests/test_ws_client.py
import asyncio
import json
import websockets
from common.ws_client import ReconnectingWS

async def test_receives_and_resubscribes_after_reconnect():
    received: list[str] = []
    connects = {"n": 0}

    async def handler(ws):
        connects["n"] += 1
        # First connection: send one message then close to force a reconnect.
        # Second connection: send a different message and keep open briefly.
        sub = await ws.recv()
        assert json.loads(sub)["cmd"] == "subscribe"
        if connects["n"] == 1:
            await ws.send("msg-A")
            await ws.close()
        else:
            await ws.send("msg-B")
            await asyncio.sleep(0.2)

    async with websockets.serve(handler, "127.0.0.1", 8799):
        client = ReconnectingWS(
            "ws://127.0.0.1:8799",
            headers_factory=lambda: {},
            on_message=lambda m: received.append(m) or asyncio.sleep(0),
            subscribe_msgs=[{"id": 1, "cmd": "subscribe", "params": {}}],
            base_backoff=0.05, max_backoff=0.1,
        )
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.6)
        client.stop()
        await asyncio.wait_for(task, timeout=2)

    assert "msg-A" in received
    assert "msg-B" in received
    assert connects["n"] >= 2  # reconnected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ws_client.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# common/ws_client.py
"""Reconnecting async WebSocket client with exponential backoff."""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
import websockets

log = logging.getLogger("ws_client")


class ReconnectingWS:
    def __init__(
        self,
        url: str,
        headers_factory: Callable[[], dict[str, str]],
        on_message: Callable[[str | bytes], Awaitable[None]],
        *,
        subscribe_msgs: list[dict] | None = None,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self.url = url
        self.headers_factory = headers_factory
        self.on_message = on_message
        self.subscribe_msgs = subscribe_msgs or []
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        backoff = self.base_backoff
        while not self._stop:
            try:
                async with websockets.connect(
                    self.url, additional_headers=self.headers_factory()
                ) as ws:
                    log.info("ws connected: %s", self.url)
                    for m in self.subscribe_msgs:
                        await ws.send(json.dumps(m))
                    backoff = self.base_backoff
                    async for raw in ws:
                        await self.on_message(raw)
                        if self._stop:
                            break
            except Exception as e:  # noqa: BLE001 - reconnect on any transport error
                if self._stop:
                    break
                log.warning("ws disconnect (%s); reconnecting in %.2fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ws_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/ws_client.py tests/test_ws_client.py
git commit -m "Add reconnecting WS client"
```

---

## Task 8: `sources/kalshi_ws/capture.py` — live capture daemon

**Files:**
- Create: `sources/kalshi_ws/capture.py`

Ties the pieces together: sign the WS handshake, subscribe to `orderbook_delta` + `trade`, stamp each inbound message with `now_ns()` immediately, write raw frames to disk. CLI with `--market`, `--minutes`, `--out`, `--env demo|prod`.

- [ ] **Step 1: Write the implementation**

```python
# sources/kalshi_ws/capture.py
"""Capture the Kalshi public WS (orderbook_delta + trade) to an append-only frame log."""
import argparse
import asyncio
import logging
from common.clock import now_ns
from common.config import kalshi_demo, kalshi_prod, KalshiConfig
from common.storage import FrameWriter
from common.ws_client import ReconnectingWS
from sources.kalshi_ws.auth import KalshiSigner

WS_PATH = "/trade-api/ws/v2"
CHANNELS = ["orderbook_delta", "trade"]


async def capture(cfg: KalshiConfig, markets: list[str], out_path: str,
                  duration_s: float | None = None) -> None:
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    writer = FrameWriter(out_path)

    def headers() -> dict[str, str]:
        return signer.headers("GET", WS_PATH)

    async def on_message(raw: str | bytes) -> None:
        t = now_ns()
        writer.write(t, raw.encode() if isinstance(raw, str) else raw)

    sub = [{"id": 1, "cmd": "subscribe",
            "params": {"channels": CHANNELS, "market_tickers": markets}}]
    client = ReconnectingWS(cfg.ws_url, headers, on_message, subscribe_msgs=sub)
    runner = asyncio.create_task(client.run())
    try:
        if duration_s is not None:
            await asyncio.sleep(duration_s)
            client.stop()
        await runner
    finally:
        client.stop()
        writer.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, help="Kalshi market ticker(s), comma-separated")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--env", choices=["demo", "prod"], default="prod")
    args = ap.parse_args()
    cfg = kalshi_prod() if args.env == "prod" else kalshi_demo()
    markets = [m.strip() for m in args.market.split(",")]
    dur = args.minutes * 60 if args.minutes else None
    try:
        import uvloop  # type: ignore
        uvloop.install()
    except Exception:
        pass
    asyncio.run(capture(cfg, markets, args.out, dur))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Short live smoke — 60 seconds against prod market data**

Uses the real ticker discovered in Task 9; until then use any active ticker from `make discover`. Example:
```bash
uv run python -m sources.kalshi_ws.capture --env prod --market <TICKER> --minutes 1 --out data/smoke.bin
```
Expected: log shows `ws connected`; `data/smoke.bin` grows to > 0 bytes. Confirm with:
```bash
uv run python -c "from common.storage import read_frames; print(sum(1 for _ in read_frames('data/smoke.bin')), 'frames')"
```
Expected: a nonzero frame count.

- [ ] **Step 3: Commit**

```bash
git add sources/kalshi_ws/capture.py
git commit -m "Add Kalshi WS capture daemon"
```

> Note: `data/` is gitignored — the capture file is not committed.

---

## Task 9: `scripts/discover_markets.py` — find the real BTC ticker

**Files:**
- Create: `scripts/discover_markets.py`

The spec's `BTCPERP` is a placeholder. Find Kalshi's actual Bitcoin market ticker via REST.

- [ ] **Step 1: Write the script**

```python
# scripts/discover_markets.py
"""List active Kalshi markets whose ticker/title mentions Bitcoin.
Run: uv run python -m scripts.discover_markets"""
import httpx
from common.config import kalshi_prod
from sources.kalshi_ws.auth import KalshiSigner

PATH = "/trade-api/v2/markets"


def main() -> None:
    cfg = kalshi_prod()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    base = (cfg.api_base or "https://api.elections.kalshi.com/trade-api/v2").replace(
        "/trade-api/v2", "")
    cursor = None
    seen = 0
    while True:
        params = {"limit": 1000, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        headers = signer.headers("GET", PATH)  # sign path without query
        r = httpx.get(base + PATH, params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        for m in data.get("markets", []):
            blob = f"{m.get('ticker','')} {m.get('title','')}".lower()
            if "btc" in blob or "bitcoin" in blob:
                print(m.get("ticker"), "|", m.get("title"))
                seen += 1
        cursor = data.get("cursor")
        if not cursor:
            break
    print(f"\n{seen} Bitcoin-related markets found.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run discovery**

Run: `make discover`
Expected: a list of BTC market tickers. Pick the one matching the project's intent (continuous/perpetual-style BTC price market). If auth for prod is not set up yet, run against demo by temporarily using `kalshi_demo()`.

- [ ] **Step 3: Record the chosen ticker**

Set `KALSHI_MARKET` in `.env` to the chosen ticker. Note the choice and the candidate list in `docs/feed-notes.md`.

- [ ] **Step 4: Commit**

```bash
git add scripts/discover_markets.py docs/feed-notes.md
git commit -m "Add Kalshi BTC market discovery script"
```

---

## Task 10: Capture real samples and document message shapes

**Files:**
- Create: `scripts/dump_message_types.py`
- Modify: `docs/feed-notes.md`
- Create: `tests/data/kalshi_samples.jsonl` (one raw message per line, hand-picked from a real capture)

- [ ] **Step 1: Write the message-type summarizer**

```python
# scripts/dump_message_types.py
"""Summarize distinct Kalshi WS message types + one example each from a capture file.
Run: uv run python -m scripts.dump_message_types data/samples.bin"""
import sys
import orjson
from common.storage import read_frames


def main(path: str) -> None:
    examples: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for _t, payload in read_frames(path):
        try:
            msg = orjson.loads(payload)
        except orjson.JSONDecodeError:
            continue
        typ = msg.get("type", "<no-type>")
        counts[typ] = counts.get(typ, 0) + 1
        examples.setdefault(typ, msg)
    for typ, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"\n### {typ}  (x{n})")
        print(orjson.dumps(examples[typ], option=orjson.OPT_INDENT_2).decode())


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 2: Capture ~2 minutes of real data and summarize**

```bash
uv run python -m sources.kalshi_ws.capture --env prod --market $(grep KALSHI_MARKET .env | cut -d= -f2) --minutes 2 --out data/samples.bin
uv run python -m scripts.dump_message_types data/samples.bin
```
Expected: printed sections for `orderbook_snapshot`, `orderbook_delta`, `trade`, plus control messages (`subscribed`, `ok`, `error`, heartbeats).

- [ ] **Step 3: Paste the real shapes into `docs/feed-notes.md`**

Under a "Kalshi WS message shapes (observed)" heading, record the exact JSON for each type. These are the ground truth the decoder is written against.

- [ ] **Step 4: Save a few raw messages as a test fixture**

Copy 1 snapshot + 2 deltas + 1 trade + 1 control message (as raw JSON, one per line) into `tests/data/kalshi_samples.jsonl`. This fixture is committed (it is public market data, no secrets).

- [ ] **Step 5: Commit**

```bash
git add scripts/dump_message_types.py docs/feed-notes.md tests/data/kalshi_samples.jsonl
git commit -m "Document observed Kalshi WS message shapes + test fixture"
```

---

## Task 11: `sources/kalshi_ws/decoder.py` — raw → Event

**Files:**
- Create: `sources/kalshi_ws/decoder.py`
- Test: `tests/test_kalshi_decoder.py`

Decoder returns `list[Event]` per raw message: a snapshot expands to one `BOOK_SNAPSHOT` event per price level; a delta → one `BOOK_DELTA`; a trade → one `TRADE`; control messages → `[]`.

> The field names below reflect the documented Kalshi v2 shapes. **In Step 1, reconcile them against the real examples captured in Task 10** (`docs/feed-notes.md`) and adjust the field access if the live payloads differ. The verify step (Step 6) fails loudly if the decoder produces zero events over the real capture.

- [ ] **Step 1: Write the failing test from the real fixture**

```python
# tests/test_kalshi_decoder.py
import orjson
from pathlib import Path
from common.event import Kind, Side, Source
from sources.kalshi_ws.decoder import decode

FIX = Path(__file__).parent / "data" / "kalshi_samples.jsonl"

def _load():
    return [line for line in FIX.read_text().splitlines() if line.strip()]

def test_control_messages_yield_nothing():
    # A 'subscribed' / 'ok' control frame decodes to no events.
    ctrl = orjson.dumps({"type": "subscribed", "id": 1, "sid": 99}).decode()
    assert decode(ctrl.encode(), t_arrival_ns=1) == []

def test_trade_decodes_to_single_trade_event():
    raw = orjson.dumps({
        "type": "trade",
        "sid": 12,
        "msg": {"market_ticker": "KXBTC", "yes_price": 52, "count": 3, "taker_side": "yes", "ts": 1700},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=555)
    assert len(events) == 1
    e = events[0]
    assert e.source == Source.KALSHI_WS
    assert e.kind == Kind.TRADE
    assert e.t_arrival_ns == 555
    assert e.market == "KXBTC"
    assert e.price == 52 and e.size == 3 and e.side == Side.YES

def test_delta_decodes_to_single_book_delta():
    raw = orjson.dumps({
        "type": "orderbook_delta",
        "sid": 12, "seq": 7,
        "msg": {"market_ticker": "KXBTC", "price": 40, "delta": -2, "side": "no"},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=1)
    assert len(events) == 1
    e = events[0]
    assert e.kind == Kind.BOOK_DELTA and e.price == 40 and e.size == -2
    assert e.side == Side.NO and e.seq == 7

def test_snapshot_expands_to_one_event_per_level():
    raw = orjson.dumps({
        "type": "orderbook_snapshot",
        "sid": 12, "seq": 1,
        "msg": {"market_ticker": "KXBTC", "yes": [[10, 100], [11, 50]], "no": [[20, 30]]},
    }).decode()
    events = decode(raw.encode(), t_arrival_ns=1)
    assert len(events) == 3
    assert all(e.kind == Kind.BOOK_SNAPSHOT and e.seq == 1 for e in events)
    yes = [e for e in events if e.side == Side.YES]
    no = [e for e in events if e.side == Side.NO]
    assert {(e.price, e.size) for e in yes} == {(10, 100), (11, 50)}
    assert {(e.price, e.size) for e in no} == {(20, 30)}

def test_every_fixture_line_decodes_without_error():
    for line in _load():
        decode(line.encode(), t_arrival_ns=1)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi_decoder.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

```python
# sources/kalshi_ws/decoder.py
"""Decode raw Kalshi WS JSON into normalized Events.
Field names verified against docs/feed-notes.md (real captured samples)."""
import orjson
from common.event import Event, Kind, Side, Source

_SIDE = {"yes": Side.YES, "no": Side.NO}


def _price_from_trade(msg: dict) -> int | None:
    # Trade carries the executed price on the taker's side.
    side = msg.get("taker_side")
    if side == "no" and "no_price" in msg:
        return msg.get("no_price")
    return msg.get("yes_price")


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    msg = orjson.loads(raw)
    typ = msg.get("type")
    body = msg.get("msg", {})
    market = body.get("market_ticker", "")
    seq = msg.get("seq")

    if typ == "trade":
        return [Event(
            source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
            kind=Kind.TRADE, price=_price_from_trade(body),
            size=body.get("count"), side=_SIDE.get(body.get("taker_side")), seq=seq)]

    if typ == "orderbook_delta":
        return [Event(
            source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
            kind=Kind.BOOK_DELTA, price=body.get("price"),
            size=body.get("delta"), side=_SIDE.get(body.get("side")), seq=seq)]

    if typ == "orderbook_snapshot":
        events: list[Event] = []
        for side_key, side_enum in (("yes", Side.YES), ("no", Side.NO)):
            for level in body.get(side_key, []) or []:
                price, size = level[0], level[1]
                events.append(Event(
                    source=Source.KALSHI_WS, t_arrival_ns=t_arrival_ns, market=market,
                    kind=Kind.BOOK_SNAPSHOT, price=price, size=size, side=side_enum, seq=seq))
        return events

    return []  # subscribed / ok / error / heartbeat / unknown
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi_decoder.py -v`
Expected: PASS (all tests). If a `msg`/field name differs from the live payload, update both the decoder and the shape notes, then re-run.

- [ ] **Step 5: Run the full suite + lint**

Run: `make test && make lint`
Expected: all tests pass; ruff clean.

- [ ] **Step 6: Verify the decoder against the real capture (no zero-event failure)**

```bash
uv run python -c "
from common.storage import read_frames
from sources.kalshi_ws.decoder import decode
n_msgs=n_events=0
for t,p in read_frames('data/samples.bin'):
    n_msgs+=1; n_events+=len(decode(p,t))
print(n_msgs,'messages ->',n_events,'events')
assert n_events>0, 'decoder produced no events — field names likely differ from live payloads'
"
```
Expected: a nonzero event count. If it asserts, reconcile field names with `docs/feed-notes.md` and fix the decoder.

- [ ] **Step 7: Commit**

```bash
git add sources/kalshi_ws/decoder.py tests/test_kalshi_decoder.py
git commit -m "Add Kalshi WS decoder (raw JSON -> Event)"
```

---

## Task 12: `sources/dz_feed/` — stubs behind the interface

**Files:**
- Create: `sources/dz_feed/capture.py`, `sources/dz_feed/decoder.py`, `sources/dz_feed/README.md`
- Test: `tests/test_dz_feed_stub.py`

The DZ feed is a second adapter with the **same interface** as `kalshi_ws`. It stays a stub until Ivan provides multicast details + wire-format doc. The stubs make the contract explicit and fail with a clear message.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dz_feed_stub.py
import inspect
import pytest
from sources.dz_feed import capture as dz_capture
from sources.dz_feed import decoder as dz_decoder

def test_decode_signature_matches_kalshi():
    sig = inspect.signature(dz_decoder.decode)
    assert list(sig.parameters) == ["raw", "t_arrival_ns"]

def test_stubs_raise_notimplemented():
    with pytest.raises(NotImplementedError):
        dz_decoder.decode(b"", 0)
    with pytest.raises(NotImplementedError):
        dz_capture.capture()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dz_feed_stub.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write the stubs**

```python
# sources/dz_feed/decoder.py
"""DoubleZero Edge feed decoder — STUB.
Implement once the wire-format doc arrives. See sources/dz_feed/README.md.
Must return list[Event] with the same contract as sources/kalshi_ws/decoder.decode."""
from common.event import Event


def decode(raw: bytes, t_arrival_ns: int) -> list[Event]:
    raise NotImplementedError(
        "DZ feed decoder not implemented — needs the wire-format doc from Ivan. "
        "See sources/dz_feed/README.md.")
```

```python
# sources/dz_feed/capture.py
"""DoubleZero Edge feed capture — STUB.
Implement once multicast group/port + interface are known. See sources/dz_feed/README.md."""


def capture(*args, **kwargs) -> None:
    raise NotImplementedError(
        "DZ feed capture not implemented — needs multicast details from Ivan. "
        "See sources/dz_feed/README.md.")
```

```markdown
<!-- sources/dz_feed/README.md -->
# DoubleZero Edge feed adapter (pending)

This adapter plugs the DZ feed into the same pipeline as `sources/kalshi_ws/`.
It is a stub until we have the following from Ivan:

1. **Multicast join details** — group address, port, and the DZ interface name to bind on the server.
2. **Wire-format doc** — message layout for trades and book snapshots/deltas, and which fields are publishable.
3. **Snapshot/recovery mechanism** — is there a snapshot, or deltas-only? How to resync after a sequence gap?

## Contract to implement
- `capture(...)`: join the multicast group on the DZ interface; stamp each packet with
  `common.clock.now_ns()` on arrival; write raw `(t_arrival_ns, bytes)` frames via `common.storage.FrameWriter`.
- `decode(raw: bytes, t_arrival_ns: int) -> list[Event]`: same return contract as the Kalshi decoder.

When both are done, the latency race and the bot consume DZ events with **zero downstream changes**.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dz_feed_stub.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sources/dz_feed tests/test_dz_feed_stub.py
git commit -m "Add DZ feed adapter stubs + interface README"
```

---

## Task 13: `docs/env.md` — environment audit + reuse decisions

**Files:**
- Modify: `docs/env.md`

Fill the environment audit (spec §0.1) and the tradebot reuse decisions (spec §0.2). No code.

- [ ] **Step 1: Fill `docs/env.md`**

Include: server specs/location and `doublezero status` output (run on the DZ server), NTP sanity check, Python/uv versions, the chosen `KALSHI_MARKET` ticker, confirmation that demo (and prod read-only, if created) keys are present as env vars (names only, never values). Then a "Reuse from tradebot" section listing, per item copied in, what was taken and why (mirror the table in the design doc), and confirmation that any keys/endpoints were stripped.

- [ ] **Step 2: Commit**

```bash
git add docs/env.md
git commit -m "Fill environment audit and reuse decisions"
```

---

## Task 14: Phase 0 acceptance — 30-minute capture + verification

**Files:**
- Create: `scripts/verify_capture.py`

Acceptance criteria (spec §0.3): 30 min simultaneous capture, sequence numbers contiguous, reconnects logged.

- [ ] **Step 1: Write the verification script**

```python
# scripts/verify_capture.py
"""Acceptance checks over a capture file: frame count, decode rate, seq contiguity.
Run: uv run python -m scripts.verify_capture data/accept.bin"""
import sys
from common.storage import read_frames
from sources.kalshi_ws.decoder import decode
from common.event import Kind


def main(path: str) -> int:
    frames = 0
    events = 0
    last_seq: int | None = None
    gaps = 0
    for t, payload in read_frames(path):
        frames += 1
        evs = decode(payload, t)
        events += len(evs)
        for e in evs:
            if e.kind in (Kind.BOOK_DELTA, Kind.BOOK_SNAPSHOT) and e.seq is not None:
                if last_seq is not None and e.seq != last_seq and e.seq != last_seq + 1:
                    gaps += 1
                last_seq = e.seq
    print(f"frames={frames} events={events} seq_gaps={gaps}")
    ok = frames > 0 and events > 0
    print("ACCEPTANCE:", "PASS" if ok else "FAIL")
    print("NOTE: any seq_gaps must be explained by a logged reconnect.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 2: Run a 30-minute capture (on the DZ server for the real acceptance)**

```bash
uv run python -m sources.kalshi_ws.capture --env prod --market $(grep KALSHI_MARKET .env | cut -d= -f2) --minutes 30 --out data/accept.bin 2>&1 | tee data/accept.log
```
Expected: runs 30 min; any disconnects appear in `data/accept.log` as `ws disconnect ... reconnecting`.

- [ ] **Step 3: Verify**

Run: `uv run python -m scripts.verify_capture data/accept.bin`
Expected: `ACCEPTANCE: PASS`, nonzero frames + events. Cross-check `seq_gaps` against reconnect lines in `data/accept.log`; unexplained gaps mean packet loss to investigate (decision point on escalating capture to Rust, spec §0.3).

- [ ] **Step 4: Record the result in `docs/log.md`**

Append: capture duration, frame/event counts, seq gaps, reconnect count, and the pass/fail verdict.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_capture.py docs/log.md
git commit -m "Add capture verification + Phase 0 acceptance run"
```

---

## Phase 0 Definition of Done

- `make test` and `make lint` are green.
- `make check-auth` returns `AUTH OK` against the demo REST API.
- A 30-minute Kalshi capture produces a frame log that decodes to a nonzero stream of normalized `Event`s, with any sequence gaps explained by logged reconnects.
- The real BTC ticker is chosen and recorded; observed message shapes are documented.
- The DZ feed adapter exists as a stub with a clear interface and a README of what Ivan must supply.
- `docs/env.md` records the environment audit and tradebot reuse decisions.

**Next:** Phase 1 (Latency Race) gets its own plan — it consumes two `Event` streams and produces the stats + PNG + split-screen TUI. Phase 2 (Book + Demo Bot) gets a third plan.
