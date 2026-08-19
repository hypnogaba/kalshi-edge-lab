"""Reconnecting async WebSocket client with exponential backoff."""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

log = logging.getLogger("ws_client")


class ReconnectingWS:
    def __init__(
        self,
        url: str,
        headers_factory: Callable[[], dict[str, str]],
        on_message: Callable[[str | bytes], Awaitable[None]],
        *,
        subscribe_msgs: list[dict] | None = None,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self.url = url
        self.headers_factory = headers_factory
        self.on_message = on_message
        self.subscribe_msgs = subscribe_msgs or []
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        backoff = self.base_backoff
        while not self._stop:
            try:
                async with websockets.connect(
                    self.url, additional_headers=self.headers_factory()
                ) as ws:
                    log.info("ws connected: %s", self.url)
                    for m in self.subscribe_msgs:
                        await ws.send(json.dumps(m))
                    backoff = self.base_backoff
                    async for raw in ws:
                        await self.on_message(raw)
                        if self._stop:
                            break
            except Exception as e:  # noqa: BLE001 - reconnect on any transport error
                if self._stop:
                    break
                log.warning("ws disconnect (%s); reconnecting in %.2fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff)
