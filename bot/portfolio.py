"""Normalize Kalshi DEMO account balance + positions into a JSON-safe snapshot used by the
bot loop (guardrails, paper PnL) and the dashboard. Parses defensively -- Kalshi API fields
may arrive as strings, or be missing entirely."""
from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _balance_dollars(balance: dict) -> float:
    if balance.get("balance_dollars") is not None:
        return _to_float(balance.get("balance_dollars"))
    return _to_float(balance.get("balance")) / 100.0


def _portfolio_value_dollars(balance: dict) -> float:
    if balance.get("portfolio_value_dollars") is not None:
        return _to_float(balance.get("portfolio_value_dollars"))
    return _to_float(balance.get("portfolio_value")) / 100.0


def snapshot(order_manager) -> dict:
    """Fetch balance + positions from `order_manager` and normalize into a JSON-safe summary:
    {"balance_dollars", "portfolio_value_dollars", "net_position", "open_markets"}.

    net_position is the sum of abs(position) across market_positions -- a conservative gross
    exposure count (a long leg and a short leg both count; they never net to zero here).
    open_markets is the count of positions with nonzero exposure.
    """
    balance = order_manager.balance() or {}
    positions = order_manager.positions() or []

    net_position = 0
    open_markets = 0
    for p in positions:
        pos = _to_int((p or {}).get("position"))
        if pos != 0:
            net_position += abs(pos)
            open_markets += 1

    return {
        "balance_dollars": _balance_dollars(balance),
        "portfolio_value_dollars": _portfolio_value_dollars(balance),
        "net_position": net_position,
        "open_markets": open_markets,
    }
