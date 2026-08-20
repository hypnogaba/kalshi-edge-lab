# scripts/live.py
"""LIVE terminal dashboard: real Kalshi BTC threshold markets + Binance spot + the demo bot's
signal, so you can watch "the bot thinking" against real public data. No keys, no DZ feed --
uses the keyless public Kalshi REST + public Binance REST.

Run (until Ctrl-C):
  uv run python -m scripts.live
One snapshot and exit (no TTY needed, good for screenshots/CI):
  uv run python -m scripts.live --once --near 6
"""
import argparse
import logging
import re
import sys
import time
from datetime import UTC, datetime

import httpx
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from bot.config import BotConfig
from bot.signal import Decision, SignalConfig, decide
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets, parse_strike

_BINANCE_SPOT_URL = "https://api.binance.com/api/v3/ticker/price"
_THRESHOLD_SUFFIX = re.compile(r"-T\d+(?:\.\d+)?$")
_SERIES = ("KXBTC", "KXBTCD")

_log = logging.getLogger(__name__)

_SIGNAL_STYLE = {
    Decision.BUY_YES: "bold green",
    Decision.BUY_NO: "bold red",
    Decision.HOLD: "dim",
}
_SIGNAL_LABEL = {
    Decision.BUY_YES: "BUY YES",
    Decision.BUY_NO: "BUY NO",
    Decision.HOLD: "HOLD",
}


def is_threshold_ticker(ticker: str) -> bool:
    """Threshold markets ('BTC >= strike?') end in -T<strike>; bucket markets (-B<strike>) are skipped."""
    return bool(_THRESHOLD_SUFFIX.search(ticker))


def fetch_spot() -> float | None:
    """One-shot Binance BTC/USDT spot. Returns None on any error -- caller must not crash."""
    try:
        r = httpx.get(_BINANCE_SPOT_URL, params={"symbol": "BTCUSDT"}, timeout=5.0)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:  # noqa: BLE001 - dashboard must keep rendering on a bad tick
        return None


def build_watchlist(rest: KalshiRestClient, near: int, spot: float) -> list[str]:
    """Near-money threshold BTC tickers across KXBTC + KXBTCD, nearest `near` by strike distance."""
    tickers: list[str] = []
    seen: set[str] = set()
    for series in _SERIES:
        try:
            markets = rest.markets(series)
        except Exception as e:  # noqa: BLE001 - one bad series must not block the other
            _log.warning("failed to fetch markets for series %s: %r", series, e)
            continue
        for m in markets:
            t = m.get("ticker")
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
    threshold = [t for t in tickers if parse_strike(t) is not None and is_threshold_ticker(t)]
    return nearest_markets(threshold, spot=spot, n=near)


def _fetch_yes_cents(rest: KalshiRestClient, ticker: str) -> int | None:
    try:
        trades = rest.trades(ticker, limit=1)
    except Exception:  # noqa: BLE001 - show "--" for this row and keep going
        return None
    if not trades:
        return None
    return round(float(trades[0]["yes_price_dollars"]) * 100)


def _header(spot: float | None) -> Panel:
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    spot_str = f"${spot:,.2f}" if spot is not None else "--"
    text = Text()
    text.append("Kalshi × DoubleZero -- live", style="bold cyan")
    text.append("   ·   ")
    text.append(f"BTC spot (Binance): {spot_str}", style="bold white")
    text.append("   ·   ")
    text.append(now_utc, style="dim")
    text.append("   ·   ")
    text.append("DRY-RUN -- bot brain, no orders", style="bold yellow")
    return Panel(text, border_style="grey50")


def _footer() -> Text:
    return Text(
        "data = public Kalshi REST (keyless) + Binance; this is exactly what the demo bot acts on.",
        style="dim italic",
    )


def render_frame(rest: KalshiRestClient, watchlist: list[str], sig_cfg: SignalConfig) -> Group:
    spot = fetch_spot()

    table = Table(expand=True, border_style="grey35")
    table.add_column("Market (BTC ≥ strike?)", overflow="fold")
    table.add_column("Strike", justify="right")
    table.add_column("Yes¢", justify="right")
    table.add_column("Spot−Strike", justify="right")
    table.add_column("Signal", justify="right")

    for ticker in watchlist:
        strike = parse_strike(ticker)
        yes_cents = _fetch_yes_cents(rest, ticker)

        strike_cell = f"${strike:,.0f}" if strike is not None else "--"
        yes_cell = str(yes_cents) if yes_cents is not None else Text("--", style="dim")

        if strike is None or spot is None:
            diff_cell = Text("--", style="dim")
        else:
            diff = spot - strike
            diff_cell = f"{diff:+,.2f}"

        if strike is None or spot is None or yes_cents is None:
            sig = Decision.HOLD
        else:
            sig = decide(strike, True, yes_cents, spot, sig_cfg)

        signal_cell = Text(_SIGNAL_LABEL[sig], style=_SIGNAL_STYLE[sig])
        table.add_row(ticker, strike_cell, yes_cell, diff_cell, signal_cell)

    if not watchlist:
        table.add_row(Text("(no threshold markets found)", style="dim"), "--", "--", "--", "--")

    return Group(_header(spot), table, _footer())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kalshi x Binance live terminal dashboard (DRY-RUN)")
    p.add_argument("--near", type=int, default=8, help="number of near-money threshold markets to watch")
    p.add_argument("--interval", type=float, default=3.0, help="refresh interval in seconds")
    p.add_argument("--minutes", type=float, default=None, help="stop after this many minutes (default: until Ctrl-C)")
    p.add_argument("--once", action="store_true", help="render one snapshot to stdout and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    console = Console()
    rest = KalshiRestClient()
    bot_cfg = BotConfig()
    sig_cfg = SignalConfig(bot_cfg.entry_dollars, bot_cfg.max_yes_cents, bot_cfg.min_yes_cents)

    try:
        seed_spot = fetch_spot()
        if seed_spot is None:
            console.print("[bold red]Could not fetch Binance BTC spot to build the watchlist.[/bold red]")
            return 1
        watchlist = build_watchlist(rest, args.near, seed_spot)

        if args.once:
            console.print(render_frame(rest, watchlist, sig_cfg))
            return 0

        deadline = time.monotonic() + args.minutes * 60 if args.minutes is not None else None
        with Live(render_frame(rest, watchlist, sig_cfg), console=console, refresh_per_second=4) as live:
            while deadline is None or time.monotonic() < deadline:
                time.sleep(args.interval)
                live.update(render_frame(rest, watchlist, sig_cfg))
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        rest.close()


if __name__ == "__main__":
    sys.exit(main())
