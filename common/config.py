"""Environment/config loading. Loads .env once; typed accessors for Kalshi."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def get(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class KalshiConfig:
    key_id: str
    private_key_path: str
    ws_url: str
    api_base: str | None = None


def kalshi_demo() -> KalshiConfig:
    return KalshiConfig(
        key_id=get("KALSHI_DEMO_KEY_ID", required=True),
        private_key_path=get("KALSHI_DEMO_PRIVATE_KEY_PATH", required=True),
        ws_url=get("KALSHI_DEMO_WS", required=True),
        api_base=get("KALSHI_DEMO_API_BASE", required=True),
    )


def kalshi_prod() -> KalshiConfig:
    return KalshiConfig(
        key_id=get("KALSHI_PROD_KEY_ID", required=True),
        private_key_path=get("KALSHI_PROD_PRIVATE_KEY_PATH", required=True),
        ws_url=get("KALSHI_PROD_WS", required=True),
        api_base=get("KALSHI_PROD_API_BASE"),
    )
