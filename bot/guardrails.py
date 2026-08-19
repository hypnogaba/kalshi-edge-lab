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
