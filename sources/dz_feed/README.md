# DoubleZero Edge feed adapter

This adapter plugs the DZ Top-of-Book & Trades feed into the same pipeline as
`sources/kalshi_ws/` and `sources/hl_ws/`. It is now implemented:

- `decoder.py` — `DzDecoder` (+ module-level `decode(raw, t_arrival_ns)`): a
  spec-accurate binary decoder for schema v3 frames (InstrumentDefinition,
  Quote, Trade; Heartbeat/EndOfSession/unknown types are skipped via the
  message Length field). Wire format:
  https://github.com/malbeclabs/edge-feed-spec/blob/main/top-of-book/spec.md
- `registry.py` — `InstrumentRegistry`: maps InstrumentID -> symbol +
  price/qty exponents, fed by `0x02 InstrumentDefinition` messages, so Quote
  and Trade raw i64/u64 values can be scaled to real prices/sizes.
- `capture.py` — a UDP multicast subscriber: joins both the mktdata port
  (Quote/Trade/Heartbeat/EndOfSession) and refdata port
  (InstrumentDefinition/ManifestSummary) on multicast group
  **233.84.178.15**, default Port Set A **mktdata=9601 / refdata=9602**;
  stamps `common.clock.now_ns()` on arrival and writes raw
  `(t_arrival_ns, bytes)` frames via `common.storage.FrameWriter`.

## Running it

`capture.py` must run on the DZ-connected server that holds an **access
pass** for the multicast group, joining on the DZ client's `doublezero1`
interface (DoubleZero's client kernel-decapsulates the GRE tunnel used for
last-mile delivery, so the application only ever sees plain UDP multicast —
`capture.py` itself does a normal `IP_ADD_MEMBERSHIP` join, no GRE handling
needed in this code). It is not runnable from a machine without that access
pass + interface.

`--selftest` verifies the receive -> store -> decode path without a real
feed, by sending one constructed valid v3 frame to a loopback socket:

```
uv run python -m sources.dz_feed.capture --selftest
```

Once both an access pass and `doublezero1` are available on the target
server, the latency race and the bot consume DZ events with **zero
downstream changes** — same `Event` contract as every other source.
