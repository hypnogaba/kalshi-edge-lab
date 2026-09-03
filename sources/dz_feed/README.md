# DoubleZero Edge feed adapter

This adapter plugs the DZ Top-of-Book & Trades feed into the same pipeline as
`sources/kalshi_ws/`, normalizing every frame to the shared `common.event.Event`
contract. It is implemented as:

- `decoder.py` — `DzDecoder` (+ module-level `decode(raw, t_arrival_ns)`): a
  spec-accurate binary decoder for schema v3 frames (InstrumentDefinition,
  Quote, Trade; Heartbeat/EndOfSession/unknown types are skipped via the
  message Length field). Wire format:
  https://github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md
- `registry.py` — `InstrumentRegistry`: maps InstrumentID -> symbol +
  price/qty exponents, fed by `0x02 InstrumentDefinition` messages, so Quote
  and Trade raw i64/u64 values can be scaled to real prices/sizes.
- `capture.py` — the receiver for both the mktdata frames
  (Quote/Trade/Heartbeat/EndOfSession) and refdata frames
  (InstrumentDefinition/ManifestSummary); stamps `common.clock.now_ns()` on
  arrival and writes raw `(t_arrival_ns, bytes)` frames via
  `common.storage.FrameWriter`.

## Running it

`capture.py` must run on the DZ-connected server that holds an **access
pass** for the multicast group. On the DoubleZero tunnel a normal
`IP_ADD_MEMBERSHIP` UDP socket receives **zero** datagrams even with the group
joined, so `capture.py` taps the `doublezero1` interface at the link layer via
`AF_PACKET` (`--link doublezero1`) and parses IP/UDP itself, keeping only the
datagrams addressed to the group on the mktdata/refdata ports. (A plain UDP
multicast join is still supported via `--iface` for environments where it
works.) It is not runnable from a machine without that access pass + interface.

`--selftest` verifies the receive -> store -> decode path without a real
feed, by sending one constructed valid v3 frame to a loopback socket:

```
uv run python -m sources.dz_feed.capture --selftest
```

Once both an access pass and `doublezero1` are available on the target
server, the latency race and the live collectors consume DZ events with
**zero downstream changes** — same `Event` contract as every other source.
