"""Binance BTCUSDT bookTicker → latest mid. Single external reference source."""
import orjson

from common.ws_client import ReconnectingWS

WS_URL = "wss://fstream.binance.com/ws/btcusdt@bookTicker"


def parse_mid(raw: str | bytes) -> float | None:
    msg = orjson.loads(raw)
    if "b" in msg and "a" in msg:
        return (float(msg["b"]) + float(msg["a"])) / 2
    return None


class BinanceRef:
    def __init__(self, url: str = WS_URL):
        self.mid: float | None = None
        self._client = ReconnectingWS(url, dict, self._on_message)

    async def _on_message(self, raw: str | bytes) -> None:
        m = parse_mid(raw)
        if m is not None:
            self.mid = m

    async def run(self) -> None:
        await self._client.run()

    def stop(self) -> None:
        self._client.stop()
