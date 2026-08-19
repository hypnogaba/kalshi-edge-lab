import orjson

from bot.decision_log import DecisionLog


def test_append_and_readback(tmp_path):
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(str(p))
    log.record(t_ns=1, market="M", kalshi_yes_cents=50, spot=69000.0,
               signal="buy_yes", action="placed", result={"order_id": "x"})
    log.close()
    lines = p.read_text().splitlines()
    assert len(lines) == 1
    row = orjson.loads(lines[0])
    assert row["market"] == "M" and row["signal"] == "buy_yes" and row["result"]["order_id"] == "x"
