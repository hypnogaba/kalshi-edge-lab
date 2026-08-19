# scripts/discover_markets.py
"""List active Kalshi markets whose ticker/title mentions Bitcoin.
Run: uv run python -m scripts.discover_markets [--env demo|prod]"""
import argparse

import httpx

from common.config import kalshi_demo, kalshi_prod
from sources.kalshi_ws.auth import KalshiSigner

PATH = "/trade-api/v2/markets"
_DEFAULT_BASE = {
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["demo", "prod"], default="demo")
    args = ap.parse_args()
    cfg = kalshi_demo() if args.env == "demo" else kalshi_prod()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    base = (cfg.api_base or _DEFAULT_BASE[args.env]).replace("/trade-api/v2", "")
    cursor = None
    seen = 0
    scanned = 0
    while True:
        params = {"limit": 1000, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        headers = signer.headers("GET", PATH)  # sign path without query
        r = httpx.get(base + PATH, params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        markets = data.get("markets", [])
        scanned += len(markets)
        for m in markets:
            blob = f"{m.get('ticker','')} {m.get('title','')}".lower()
            if "btc" in blob or "bitcoin" in blob:
                print(m.get("ticker"), "|", m.get("title"))
                seen += 1
        cursor = data.get("cursor")
        if not cursor or not markets:
            break
    print(f"\nscanned {scanned} open markets; {seen} Bitcoin-related.")


if __name__ == "__main__":
    main()
