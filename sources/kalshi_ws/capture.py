# sources/kalshi_ws/capture.py
"""Capture the Kalshi public WS (orderbook_delta + trade) to an append-only frame log."""
import argparse
import asyncio
import logging

from common.clock import now_ns
from common.config import KalshiConfig, kalshi_demo, kalshi_prod
from common.storage import FrameWriter
from common.ws_client import ReconnectingWS
from sources.kalshi_ws.auth import KalshiSigner

WS_PATH = "/trade-api/ws/v2"
CHANNELS = ["orderbook_delta", "trade"]


async def capture(cfg: KalshiConfig, markets: list[str], out_path: str,
                  duration_s: float | None = None) -> None:
    signer = KalshiSigner(cfg.key_id, cfg.private_key_path)
    writer = FrameWriter(out_path)

    def headers() -> dict[str, str]:
        return signer.headers("GET", WS_PATH)

    async def on_message(raw: str | bytes) -> None:
        t = now_ns()
        writer.write(t, raw.encode() if isinstance(raw, str) else raw)

    sub = [{"id": 1, "cmd": "subscribe",
            "params": {"channels": CHANNELS, "market_tickers": markets}}]
    client = ReconnectingWS(cfg.ws_url, headers, on_message, subscribe_msgs=sub)
    runner = asyncio.create_task(client.run())
    try:
        if duration_s is not None:
            await asyncio.sleep(duration_s)
            client.stop()
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
        else:
            await runner
    finally:
        client.stop()
        writer.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, help="Kalshi market ticker(s), comma-separated")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--env", choices=["demo", "prod"], default="prod")
    args = ap.parse_args()
    cfg = kalshi_prod() if args.env == "prod" else kalshi_demo()
    markets = [m.strip() for m in args.market.split(",")]
    dur = args.minutes * 60 if args.minutes else None
    try:
        import uvloop  # type: ignore
        uvloop.install()
    except Exception:  # noqa: BLE001, S110 - uvloop is an optional speedup
        pass
    asyncio.run(capture(cfg, markets, args.out, dur))


if __name__ == "__main__":
    main()
