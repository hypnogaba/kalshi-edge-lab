"""Vercel serverless function: GET /api/state.

Computes the live dashboard state on each request (no background process, so it
fits serverless): Binance BTC spot + near-the-money Kalshi threshold markets +
the naive bot signal. Stdlib only (urllib) — no build deps.

The signal + strike logic is vendored here (mirrors ``bot/signal.py`` and
``sources/kalshi_rest/selector.py``) so the function is self-contained for
serverless bundling. Keep the two in sync if the strategy changes.
"""
from http.server import BaseHTTPRequestHandler
import json
import re
import urllib.parse
import urllib.request

_STRIKE = re.compile(r"-[TB](\d+(?:\.\d+)?)$")
_KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
_BINANCE = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

# signal tuning — mirrors bot/config.py BotConfig defaults
_ENTRY_DOLLARS = 50.0
_MAX_YES_CENTS = 90
_MIN_YES_CENTS = 10
_NEAR = 6


def _parse_strike(ticker):
    m = _STRIKE.search(ticker)
    return float(m.group(1)) if m else None


def _decide(strike, yes_cents, spot):
    if yes_cents is None or spot is None or strike is None:
        return "hold"
    dist = spot - strike
    if abs(dist) < _ENTRY_DOLLARS:
        return "hold"
    if dist > 0 and yes_cents < _MAX_YES_CENTS:
        return "buy_yes"
    if dist < 0 and yes_cents > _MIN_YES_CENTS:
        return "buy_no"
    return "hold"


def _get_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "edge-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https only)
        return json.load(r)


def _compute_state():
    spot = float(_get_json(_BINANCE)["price"])
    tickers = []
    for series in ("KXBTC", "KXBTCD"):
        data = _get_json(f"{_KALSHI}/markets?series_ticker={series}&status=open&limit=200")
        tickers += [m["ticker"] for m in data.get("markets", [])]
    threshold = [t for t in tickers if re.search(r"-T\d", t)]
    threshold.sort(key=lambda t: abs((_parse_strike(t) or 1e18) - spot))
    markets = []
    for ticker in threshold[:_NEAR]:
        yes_cents = None
        try:
            trades = _get_json(
                f"{_KALSHI}/markets/trades?ticker={urllib.parse.quote(ticker)}&limit=1"
            ).get("trades", [])
            if trades:
                yes_cents = round(float(trades[0]["yes_price_dollars"]) * 100)
        except Exception:  # noqa: BLE001 - one bad market must not fail the response
            yes_cents = None
        strike = _parse_strike(ticker)
        markets.append({
            "ticker": ticker, "strike": strike,
            "yes_cents": yes_cents, "signal": _decide(strike, yes_cents, spot),
        })
    return {"spot": spot, "markets": markets, "dz_feed": "pending", "race": None}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (Vercel Python handler contract)
        try:
            payload = json.dumps(_compute_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "s-maxage=5, stale-while-revalidate=15")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
