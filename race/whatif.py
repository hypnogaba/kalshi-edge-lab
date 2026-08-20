"""What-if counterfactual engine: quantify the DoubleZero edge feed's per-trade
latency advantage in cents/dollars, on real CAPTURED data.

Model
-----
For each trade matched across both feeds (see race.match), the edge-fed bot
could have acted the instant the DoubleZero feed delivered it, at time `t_dz`
and price `edge_price` (that trade's top-of-book trade price -- no slippage,
no fees). A public-only bot doesn't learn of that same trade until
`delta_ns = t_public - t_dz` later.

The matched public copy of the trade has, by construction, the SAME price as
the edge copy (it's the same underlying trade seen twice) -- so comparing
those two directly would trivially always show zero advantage and would tell
us nothing. What actually matters is: once the public-only bot catches up
(at `t_dz + delta_ns`), what price is it actually looking at? That's the next
DIFFERENT public trade for the same market, strictly after that moment (the
market may have kept moving in the meantime). `public_price` is that price;
if no further public trade for the market lands within a short follow window
(`window_ns`, reused for simplicity), we fall back to `edge_price` -- i.e.
"nothing happened, so no advantage" rather than inventing a number.

edge_adv = public_price - edge_price. Positive means the market moved against
a bot that could only act once the public feed caught up -- i.e. acting on
the edge feed was cheaper/better.

Honesty / limitations (read before citing a number from this module)
----------------------------------------------------------------------
- This is a MODEL of a counterfactual, not a backtest of real fills. It
  assumes top-of-book trade prices are tradeable with no slippage, no fees,
  no size limits, and no adverse selection, and that the edge bot has no
  reaction latency of its own beyond the feed delivering the data.
- It only covers trades that MATCHED across both feeds (race.match); it says
  nothing about trades one feed missed, or about the two feeds disagreeing
  about a trade's own price/size (that would fail to match at all).
- `contract_count` is a flat multiplier for illustration, not a claim that
  any of these trades were actually tradeable at that size.
"""
from statistics import median

from common.event import Kind
from race.match import Frame, match_trades

_DEFAULT_CONTRACT_COUNT = 1


def whatif_stats(opportunities: list[dict], contract_count: int = _DEFAULT_CONTRACT_COUNT) -> dict:
    """Aggregate a list of opportunity dicts (see build_opportunities) into
    summary stats. Pure, no I/O.

    Each opportunity: {"delta_ns": int, "edge_price": float, "public_price": float}
    (prices in cents). edge_adv = public_price - edge_price per opportunity.
    """
    if not opportunities:
        return {"n": 0}

    n = len(opportunities)
    delta_ms = [o["delta_ns"] / 1e6 for o in opportunities]
    edge_adv = [o["public_price"] - o["edge_price"] for o in opportunities]
    wins = sum(1 for a in edge_adv if a > 0)

    return {
        "n": n,
        "median_delta_ms": round(median(delta_ms), 3),
        "avg_edge_cents": round(sum(edge_adv) / n, 3),
        "total_edge_dollars": round(sum(edge_adv) / 100 * contract_count, 2),
        "win_rate": round(100 * wins / n, 1),
    }


def build_opportunities(
    public_trades: list[Frame], dz_trades: list[Frame], *, window_ns: int,
) -> list[dict]:
    """Build what-if opportunities from two raw (t_arrival_ns, Event) TRADE
    streams captured on one host's clock (same shape race.match.match_trades
    uses).

    Matches dz_trades against public_trades (dz first, so MatchedPair.price
    is the price the edge feed itself saw, and MatchedPair.delta_ns comes out
    as t_public - t_dz -- see race.match for the matching rule). For each
    matched pair, looks up the next public trade for the same market strictly
    after the public feed's own catch-up point; see the model note in this
    module's docstring for why the matched trade's own (trivially identical)
    price isn't used directly.
    """
    pairs, _discarded_dz, _discarded_public = match_trades(
        dz_trades, public_trades, window_ns=window_ns,
    )

    opportunities: list[dict] = []
    for pair in pairs:
        t_dz = pair.t_a_ns
        delta_ns = pair.delta_ns
        edge_price = pair.price
        t_public = t_dz + delta_ns  # this pair's own public arrival, exactly

        best_t: int | None = None
        best_price: float | int | None = None
        for t, ev in public_trades:
            if ev.kind != Kind.TRADE or ev.market != pair.market:
                continue
            if t <= t_public:
                continue
            if best_t is None or t < best_t:
                best_t = t
                best_price = ev.price

        if best_t is not None and (best_t - t_public) <= window_ns:
            public_price = best_price
        else:
            public_price = edge_price

        opportunities.append({
            "delta_ns": delta_ns,
            "edge_price": edge_price,
            "public_price": public_price,
        })
    return opportunities
