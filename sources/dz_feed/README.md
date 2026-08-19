# DoubleZero Edge feed adapter (pending)

This adapter plugs the DZ feed into the same pipeline as `sources/kalshi_ws/`.
It is a stub until we have the following from Ivan:

1. **Multicast join details** — group address, port, and the DZ interface name to bind on the server.
2. **Wire-format doc** — message layout for trades and book snapshots/deltas, and which fields are publishable.
3. **Snapshot/recovery mechanism** — is there a snapshot, or deltas-only? How to resync after a sequence gap?

## Contract to implement
- `capture(...)`: join the multicast group on the DZ interface; stamp each packet with
  `common.clock.now_ns()` on arrival; write raw `(t_arrival_ns, bytes)` frames via `common.storage.FrameWriter`.
- `decode(raw: bytes, t_arrival_ns: int) -> list[Event]`: same return contract as the Kalshi decoder.

When both are done, the latency race and the bot consume DZ events with **zero downstream changes**.
