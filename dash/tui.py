"""Rich dashboard for the Phase 2 demo bot.

`render(state)` is a pure function: dict -> rich renderable. `main()` tails a decision-log
JSONL file and refreshes a live view — it works standalone, with no bot running, purely by
reading whatever `bot.run` has appended so far.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import orjson
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

_DEFAULT_DECISION_LOG = "data/decisions.jsonl"
_DEFAULT_TAIL_ROWS = 20
_DEFAULT_REFRESH_S = 1.0

_DARK_STYLE = "bright_white on grey11"
_HEADER_STYLE = "bold cyan"
_HOLD_STYLE = "grey58"
_PLACED_STYLE = "bold green"
_BLOCKED_STYLE = "bold yellow"
_BUY_YES_STYLE = "bold green"
_BUY_NO_STYLE = "bold red"


def _signal_style(signal: str) -> str:
    if signal == "buy_yes":
        return _BUY_YES_STYLE
    if signal == "buy_no":
        return _BUY_NO_STYLE
    return _HOLD_STYLE


def _action_style(action: str) -> str:
    if action == "placed":
        return _PLACED_STYLE
    if action == "blocked":
        return _BLOCKED_STYLE
    return _HOLD_STYLE


def render(state: dict[str, Any]) -> Group:
    """Build a dark, screenshot-friendly panel from a state dict.

    Expected keys: spot (float|None), markets (dict[str, dict] with "yes_cents"/"signal"),
    position (int), pnl_cents (int), decisions (list of decision-log rows, most recent first).
    """
    spot = state.get("spot")
    position = state.get("position", 0)
    pnl_cents = state.get("pnl_cents", 0)
    markets: dict[str, dict[str, Any]] = state.get("markets", {})
    decisions: list[dict[str, Any]] = state.get("decisions", [])

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style=_HEADER_STYLE)
    summary.add_column(style=_DARK_STYLE)
    summary.add_row("spot (BTC/USDT)", f"${spot:,.2f}" if spot is not None else "—")
    summary.add_row("position", str(position))
    summary.add_row("paper PnL", f"{pnl_cents / 100:+.2f} USD")

    markets_table = Table(title="Watched markets", style=_DARK_STYLE, header_style=_HEADER_STYLE)
    markets_table.add_column("ticker")
    markets_table.add_column("yes (cents)", justify="right")
    markets_table.add_column("signal")
    for ticker, m in markets.items():
        yes_cents = m.get("yes_cents")
        signal = m.get("signal", "hold")
        markets_table.add_row(
            ticker,
            str(yes_cents) if yes_cents is not None else "—",
            f"[{_signal_style(signal)}]{signal}[/]",
        )
    if not markets:
        markets_table.add_row("—", "—", "—")

    decisions_table = Table(title="Recent decisions", style=_DARK_STYLE, header_style=_HEADER_STYLE)
    decisions_table.add_column("t_ns", justify="right")
    decisions_table.add_column("market")
    decisions_table.add_column("yes (cents)", justify="right")
    decisions_table.add_column("spot", justify="right")
    decisions_table.add_column("signal")
    decisions_table.add_column("action")
    decisions_table.add_column("result")
    for row in decisions:
        yes_cents = row.get("kalshi_yes_cents")
        row_spot = row.get("spot")
        action = row.get("action", "")
        signal = row.get("signal", "")
        decisions_table.add_row(
            str(row.get("t_ns", "")),
            str(row.get("market", "")),
            str(yes_cents) if yes_cents is not None else "—",
            f"{row_spot:,.2f}" if row_spot is not None else "—",
            f"[{_signal_style(signal)}]{signal}[/]",
            f"[{_action_style(action)}]{action}[/]",
            str(row.get("result") or ""),
        )
    if not decisions:
        decisions_table.add_row("—", "—", "—", "—", "—", "—", "—")

    return Group(Panel(summary, title="Bot state", style=_DARK_STYLE), markets_table, decisions_table)


def _read_decisions(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(orjson.loads(line))
        except orjson.JSONDecodeError:  # tolerate a partially-written last line
            continue
    return rows


def build_state(rows: list[dict[str, Any]], tail_rows: int = _DEFAULT_TAIL_ROWS) -> dict[str, Any]:
    """Derive dashboard state purely from decision-log rows (most recent last, as written)."""
    markets: dict[str, dict[str, Any]] = {}
    spot = None
    position = 0
    for row in rows:
        ticker = row.get("market")
        if ticker:
            markets[ticker] = {"yes_cents": row.get("kalshi_yes_cents"), "signal": row.get("signal")}
        if row.get("spot") is not None:
            spot = row["spot"]
        if row.get("action") == "placed":
            position += 1
    return {
        "spot": spot,
        "markets": markets,
        "position": position,
        "pnl_cents": 0,  # paper: no fills modeled in dry-run
        "decisions": list(reversed(rows[-tail_rows:])),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tail the Phase 2 bot decision log as a live dashboard")
    p.add_argument("--decision-log", type=str, default=_DEFAULT_DECISION_LOG)
    p.add_argument("--lines", type=int, default=_DEFAULT_TAIL_ROWS, help="rows to show")
    p.add_argument("--interval", type=float, default=_DEFAULT_REFRESH_S, help="refresh interval (s)")
    p.add_argument("--once", action="store_true", help="render once and exit (no live refresh)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    console = Console()

    if args.once:
        rows = _read_decisions(args.decision_log)
        console.print(render(build_state(rows, args.lines)))
        return

    with Live(console=console, refresh_per_second=4, screen=False) as live:
        while True:
            rows = _read_decisions(args.decision_log)
            live.update(render(build_state(rows, args.lines)))
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
