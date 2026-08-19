import pytest

from bot.guardrails import GuardrailBreach, Guardrails


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
