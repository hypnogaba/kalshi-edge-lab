# sources/hl_ws/capture.py
"""Capture the public Hyperliquid WS (trades + bbo) to an append-only frame log."""
import argparse
import asyncio
import logging

from common.clock import now_ns
from common.storage import FrameWriter
from common.ws_client import ReconnectingWS

HL_WS_URL = "wss://api.hyperliquid.xyz/ws"


async def capture(coin: str, out_path: str, duration_s: float | None = None) -> None:
    writer = FrameWriter(out_path)

    async def on_message(raw: str | bytes) -> None:
        t = now_ns()
        writer.write(t, raw.encode() if isinstance(raw, str) else raw)

    sub = [
        {"method": "subscribe", "subscription": {"type": "trades", "coin": coin}},
        {"method": "subscribe", "subscription": {"type": "bbo", "coin": coin}},
    ]
    client = ReconnectingWS(HL_WS_URL, dict, on_message, subscribe_msgs=sub)
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
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    dur = args.minutes * 60 if args.minutes else None
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:  # noqa: BLE001, S110 - uvloop is an optional speedup
        pass
    asyncio.run(capture(args.coin, args.out, dur))


if __name__ == "__main__":
    main()
