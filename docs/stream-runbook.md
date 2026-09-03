# Stream runbook

What to show on air, in what order, and what not to claim. Written for a live
audience of traders who will check every number.

## Before you go live

```bash
doublezero status                 # BGP Session Up, Frankfurt, S:edge-kalshi-perps-tob
systemctl is-active dz-feed dz-race edge-duel edge-web
curl -s localhost:8080/api/duel | jq '.head_to_head'
```

`head_to_head.n` is the number of shared chances in the window. Under ~200 the
fill rates still jump around; leave `edge-duel` running for a few hours before
the stream and do not restart it, because the window lives in memory.

Two pages, both on the same host:

- `/` the benchmark: how much sooner the data arrives.
- `/duel` the demo: what that buys, two bots side by side.

## The three beats

**1. The pipe (30 seconds, terminal).** `doublezero status`. One line shows the
tunnel is up, the metro, and which multicast group is joined. This is the whole
onboarding: a Linux box with a public IP, an access pass, one `connect` command.

**2. The measurement (2 minutes, `/`).** Same trade, two ways into one machine,
matched by the venue's own timestamp, timed on one monotonic clock. No
cross-machine skew, because there is only one machine. Median lead and win rate
are live over a rolling window.

**3. The consequence (the rest, `/duel`).** The same strategy runs twice, one
copy per feed. Both react to the same print, both are filled against the same
order book, each judged when its own order could have arrived. The gap between
them is the feed delta and nothing else.

## What to say, and what not to

Say: **you get the price you aimed at more often.** That is what the fill rates
measure and it is the honest claim.

Do not say faster means more profitable. The demo strategy crosses the spread on
purpose, so its mark-out is negative for both bots; speed changes whether the
quote is still there, not whether the rule is any good. If someone asks about
P&L, say that out loud. It is on the page anyway.

Do not present paper fills as fills. They model no queue position, no fees and
no partial fills. Both bots get the same free pass, which is why the comparison
survives even though the absolute numbers are not a promise.

Expect the public bot to win sometimes. It does, and showing it is the reason
anyone should believe the rest.

## If it goes quiet on air

Prints large enough to act on arrive in bursts. The `recent` table keeps the
last 20 duels, so there is always something on screen even in a lull. Quiet
markets are also the honest case: when nothing moves between the two arrival
times, both bots fill, and that shows up as "same outcome".

## Numbers as of the last soak

Measured on the Frankfurt host, one clock, over the rolling window:

- median lead over the public feed: about 7.4 ms, on roughly 97% of matched trades
- matched across 12 of the 13 crypto perps, not BTC alone
- duel fill rates: DoubleZero in the high 80s to mid 90s, public in the 60s to 70s

Re-read them off the pages before quoting; they move.
