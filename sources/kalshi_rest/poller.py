"""Poll public Kalshi prod REST for selected markets; write tagged raw frames.
Frame envelope: {"kind":"trade"|"orderbook","ticker":...,"data":...}."""
import argparse
import asyncio
import logging
import time

import orjson

from common.clock import now_ns
from common.storage import FrameWriter
from sources.kalshi_rest.client import KalshiRestClient
from sources.kalshi_rest.selector import nearest_markets

log = logging.getLogger("kalshi_rest.poller")


def _btc_spot() -> float:
    import httpx
    r = httpx.get("https://api.binance.com/api/v3/ticker/price",
                  params={"symbol": "BTCUSDT"}, timeout=10.0)
    return float(r.json()["price"])


async def poll(tickers: list[str], out_path: str, interval_s: float,
               duration_s: float | None) -> None:
    client = KalshiRestClient()
    writer = FrameWriter(out_path)
    seen: set[str] = set()
    deadline = None if duration_s is None else time.monotonic() + duration_s
    try:
        while deadline is None or time.monotonic() < deadline:
            for t in tickers:
                try:
                    ob = client.orderbook(t)
                    writer.write(now_ns(), orjson.dumps({"kind": "orderbook", "ticker": t, "data": ob}))
                    for tr in client.trades(t, limit=50):
                        tid = tr.get("trade_id")
                        if tid and tid not in seen:
                            seen.add(tid)
                            writer.write(now_ns(), orjson.dumps({"kind": "trade", "ticker": t, "data": tr}))
                except Exception as e:  # noqa: BLE001 - keep polling other markets
                    log.warning("poll error for %s: %s", t, e)
            await asyncio.sleep(interval_s)
    finally:
        writer.close()
        client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="KXBTC")
    ap.add_argument("--near", type=int, default=6, help="poll N near-the-money markets")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    client = KalshiRestClient()
    tickers_all = [m["ticker"] for m in client.markets(args.series)]
    client.close()
    tickers = nearest_markets(tickers_all, _btc_spot(), args.near)
    log.info("polling %d markets: %s", len(tickers), tickers)
    dur = args.minutes * 60 if args.minutes else None
    asyncio.run(poll(tickers, args.out, args.interval, dur))


if __name__ == "__main__":
    main()
