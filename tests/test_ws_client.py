import asyncio
import json

import websockets

from common.ws_client import ReconnectingWS


async def test_receives_and_resubscribes_after_reconnect():
    received: list[str] = []
    connects = {"n": 0}

    async def handler(ws):
        connects["n"] += 1
        sub = await ws.recv()
        assert json.loads(sub)["cmd"] == "subscribe"
        if connects["n"] == 1:
            await ws.send("msg-A")
            await ws.close()
        else:
            await ws.send("msg-B")
            await asyncio.sleep(0.2)

    async with websockets.serve(handler, "127.0.0.1", 8799):
        client = ReconnectingWS(
            "ws://127.0.0.1:8799",
            headers_factory=dict,
            on_message=lambda m: received.append(m) or asyncio.sleep(0),
            subscribe_msgs=[{"id": 1, "cmd": "subscribe", "params": {}}],
            base_backoff=0.05, max_backoff=0.1,
        )
        task = asyncio.create_task(client.run())
        await asyncio.sleep(0.6)
        client.stop()
        await asyncio.wait_for(task, timeout=2)

    assert "msg-A" in received
    assert "msg-B" in received
    assert connects["n"] >= 2
