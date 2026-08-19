"""Pick near-the-money Kalshi BTC markets from ticker strikes."""
import re

_STRIKE = re.compile(r"-[TB](\d+(?:\.\d+)?)$")


def parse_strike(ticker: str) -> float | None:
    m = _STRIKE.search(ticker)
    return float(m.group(1)) if m else None


def nearest_markets(tickers: list[str], spot: float, n: int) -> list[str]:
    scored = []
    for t in tickers:
        s = parse_strike(t)
        if s is not None:
            scored.append((abs(s - spot), t))
    scored.sort()
    return [t for _, t in scored[:n]]
