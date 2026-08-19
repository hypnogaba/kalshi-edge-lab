"""Append-only JSONL decision log — every decision the bot makes. This log is later content."""
import orjson


class DecisionLog:
    def __init__(self, path: str):
        self._f = open(path, "ab", buffering=0)  # noqa: SIM115 - kept open across record() calls

    def record(self, t_ns: int, market: str, kalshi_yes_cents: int | None,
               spot: float | None, signal: str, action: str, result: dict | None) -> None:
        row = {"t_ns": t_ns, "market": market, "kalshi_yes_cents": kalshi_yes_cents,
               "spot": spot, "signal": signal, "action": action, "result": result}
        self._f.write(orjson.dumps(row) + b"\n")

    def close(self) -> None:
        self._f.close()
