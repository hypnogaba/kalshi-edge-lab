# scripts/check_auth.py
"""Live smoke test: signed GET /portfolio/balance against Kalshi demo REST.
Run: uv run python -m scripts.check_auth"""
import sys
import httpx
from common.config import kalshi_demo
from sources.kalshi_ws.auth import KalshiSigner

PATH = "/trade-api/v2/portfolio/balance"


def main() -> int:
    cfg = kalshi_demo()
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    base = cfg.api_base.replace("/trade-api/v2", "")  # host root
    headers = signer.headers("GET", PATH)
    r = httpx.get(base + PATH, headers=headers, timeout=10.0)
    print(f"HTTP {r.status_code}")
    print(r.text[:500])
    if r.status_code == 200:
        print("AUTH OK — demo credentials work.")
        return 0
    print("AUTH FAILED — check KALSHI_DEMO_KEY_ID / private key / clock skew.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
