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
