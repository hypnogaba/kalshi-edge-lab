"""Rich split-screen TUI for the latency race.

`render(state)` is a pure function: dict -> rich renderable. Left column is
the public Hyperliquid WS top-of-book, right column is the DZ edge feed
top-of-book, and a big panel below shows the running latency delta (last
matched delta_ms + rolling p50). `main()` replays a JSONL file of state
snapshots for a demo, or shows a placeholder state with no file given —
it works standalone with no live feeds running.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import orjson
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

_DEFAULT_REFRESH_S = 0.5

_DARK_STYLE = "bright_white on grey11"
_HEADER_STYLE = "bold cyan"
_BID_STYLE = "bold green"
_ASK_STYLE = "bold red"
_DELTA_POS_STYLE = "bold red"  # positive = B (dz feed) arrived later -> public was first
_DELTA_NEG_STYLE = "bold green"  # negative = dz feed arrived first


def _book_panel(title: str, book: dict[str, Any]) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=_HEADER_STYLE)
    table.add_column(style=_DARK_STYLE, justify="right")

    bid = book.get("bid")
    bid_size = book.get("bid_size")
    ask = book.get("ask")
    ask_size = book.get("ask_size")

    table.add_row(
        "bid", f"[{_BID_STYLE}]{bid:,.2f}[/] x {bid_size:g}" if bid is not None else "—",
    )
    table.add_row(
        "ask", f"[{_ASK_STYLE}]{ask:,.2f}[/] x {ask_size:g}" if ask is not None else "—",
    )
    return Panel(table, title=title, style=_DARK_STYLE)


def _delta_panel(last_delta_ms: float | None, p50_delta_ms: float | None) -> Panel:
    if last_delta_ms is None:
        body = Align.center("[grey58]no matched trades yet[/]")
    else:
        style = _DELTA_POS_STYLE if last_delta_ms >= 0 else _DELTA_NEG_STYLE
        p50_str = f"{p50_delta_ms:+.3f} ms" if p50_delta_ms is not None else "—"
        body = Align.center(
            f"[{style}]{last_delta_ms:+.3f} ms[/]   (rolling p50: {p50_str})",
            vertical="middle",
        )
    return Panel(body, title="latency delta (dz_feed - hl_ws)", style=_DARK_STYLE)


def render(state: dict[str, Any]) -> Group:
    """Build a dark, screenshot-friendly split-screen view from a state dict.

    Expected keys: hl_ws (dict with market/bid/bid_size/ask/ask_size),
    dz_feed (same shape), last_delta_ms (float|None), p50_delta_ms (float|None).
    """
    hl_ws: dict[str, Any] = state.get("hl_ws", {})
    dz_feed: dict[str, Any] = state.get("dz_feed", {})
    last_delta_ms = state.get("last_delta_ms")
    p50_delta_ms = state.get("p50_delta_ms")

    columns = Table.grid(expand=True)
    columns.add_column(ratio=1)
    columns.add_column(ratio=1)
    columns.add_row(
        _book_panel(f"public HL WS ({hl_ws.get('market', '—')})", hl_ws),
        _book_panel(f"DZ edge feed ({dz_feed.get('market', '—')})", dz_feed),
    )

    return Group(columns, _delta_panel(last_delta_ms, p50_delta_ms))


def _read_snapshots(path: str) -> list[dict[str, Any]]:
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


def _placeholder_state() -> dict[str, Any]:
    return {
        "hl_ws": {"market": "BTC"},
        "dz_feed": {"market": "BTC"},
        "last_delta_ms": None,
        "p50_delta_ms": None,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live split-screen latency race TUI")
    p.add_argument("--replay", type=str, default=None, help="JSONL file of state snapshots")
    p.add_argument("--interval", type=float, default=_DEFAULT_REFRESH_S, help="refresh interval (s)")
    p.add_argument("--once", action="store_true", help="render once and exit (no live refresh)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    console = Console()

    if args.once or not args.replay:
        rows = _read_snapshots(args.replay) if args.replay else []
        state = rows[-1] if rows else _placeholder_state()
        console.print(render(state))
        return

    with Live(console=console, refresh_per_second=4, screen=False) as live:
        while True:
            rows = _read_snapshots(args.replay)
            state = rows[-1] if rows else _placeholder_state()
            live.update(render(state))
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
