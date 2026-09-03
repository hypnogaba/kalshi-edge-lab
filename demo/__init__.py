"""Two identical bots, one on each feed, so the latency number becomes a decision.

`scripts.dz_latency_race` answers "how much sooner does the DoubleZero feed
arrive". This package answers the question a trader actually asks next: "what
does that buy me". It runs the SAME strategy twice in one process on one clock,
one instance fed by the DoubleZero edge feed and one by Kalshi's public
WebSocket, and compares what each one could actually get filled at.
"""
