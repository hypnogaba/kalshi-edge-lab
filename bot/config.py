"""Bot tunables (strategy + guardrail ceilings + file paths). No secrets here —
Kalshi credentials live in common/config.py and are read from the environment there."""
import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v is not None else default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v is not None else default


@dataclass(frozen=True)
class BotConfig:
    series: str = "KXBTCD"
    near: int = 6
    poll_interval_s: float = 3.0
    entry_dollars: float = 50.0
    max_yes_cents: int = 90
    min_yes_cents: int = 10
    order_count: int = 1
    order_price_cents: int = 5
    max_position: int = 5
    max_orders_per_min: int = 6
    max_daily_loss_cents: int = 5000
    kill_switch_path: str = "data/KILL"
    decision_log_path: str = "data/decisions.jsonl"

    @classmethod
    def from_env(cls) -> "BotConfig":
        d = cls()
        return cls(
            series=_env_str("BOT_SERIES", d.series),
            near=_env_int("BOT_NEAR", d.near),
            poll_interval_s=_env_float("BOT_POLL_INTERVAL_S", d.poll_interval_s),
            entry_dollars=_env_float("BOT_ENTRY_DOLLARS", d.entry_dollars),
            max_yes_cents=_env_int("BOT_MAX_YES_CENTS", d.max_yes_cents),
            min_yes_cents=_env_int("BOT_MIN_YES_CENTS", d.min_yes_cents),
            order_count=_env_int("BOT_ORDER_COUNT", d.order_count),
            order_price_cents=_env_int("BOT_ORDER_PRICE_CENTS", d.order_price_cents),
            max_position=_env_int("BOT_MAX_POSITION", d.max_position),
            max_orders_per_min=_env_int("BOT_MAX_ORDERS_PER_MIN", d.max_orders_per_min),
            max_daily_loss_cents=_env_int("BOT_MAX_DAILY_LOSS_CENTS", d.max_daily_loss_cents),
            kill_switch_path=_env_str("BOT_KILL_SWITCH_PATH", d.kill_switch_path),
            decision_log_path=_env_str("BOT_DECISION_LOG_PATH", d.decision_log_path),
        )
