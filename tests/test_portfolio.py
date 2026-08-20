from bot.portfolio import snapshot


class _FakeOrderManager:
    def __init__(self, balance: dict, positions: list[dict]):
        self._balance = balance
        self._positions = positions

    def balance(self) -> dict:
        return self._balance

    def positions(self) -> list[dict]:
        return self._positions


def test_snapshot_normal_parse():
    om = _FakeOrderManager(
        balance={"balance": 10050, "balance_dollars": 100.50, "portfolio_value": 10500},
        positions=[{"position": 3}, {"position": -2}, {"position": 0}],
    )
    out = snapshot(om)
    assert out == {
        "balance_dollars": 100.50,
        "portfolio_value_dollars": 105.0,
        "net_position": 5,
        "open_markets": 2,
    }


def test_snapshot_empty_positions():
    om = _FakeOrderManager(
        balance={"balance": 500, "balance_dollars": 5.0, "portfolio_value": 500},
        positions=[],
    )
    out = snapshot(om)
    assert out["net_position"] == 0
    assert out["open_markets"] == 0
    assert out["balance_dollars"] == 5.0
    assert out["portfolio_value_dollars"] == 5.0


def test_snapshot_missing_and_string_fields():
    om = _FakeOrderManager(
        # no balance_dollars/portfolio_value_dollars -- must fall back to cents fields as strings
        balance={"balance": "10050", "portfolio_value": "10500"},
        positions=[{"position": "3"}, {}, {"position": None}],
    )
    out = snapshot(om)
    assert out["balance_dollars"] == 100.50
    assert out["portfolio_value_dollars"] == 105.0
    assert out["net_position"] == 3
    assert out["open_markets"] == 1


def test_snapshot_missing_balance_dict_entirely():
    om = _FakeOrderManager(balance={}, positions=[{"position": 1}])
    out = snapshot(om)
    assert out["balance_dollars"] == 0.0
    assert out["portfolio_value_dollars"] == 0.0
    assert out["net_position"] == 1
    assert out["open_markets"] == 1
