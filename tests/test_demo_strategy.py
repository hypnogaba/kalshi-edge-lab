"""The rule must fire only when being early can matter."""
from common.event import Event, Kind, Side, Source
from demo.strategy import FollowThePrint, StrategyConfig

MKT = "KXBTCPERP"


def quote(bid: float, ask: float, t_ns: int) -> list[Event]:
    return [
        Event(source=Source.DZ_FEED, t_arrival_ns=t_ns, market=MKT, kind=Kind.QUOTE,
              side=Side.BID, price=bid, size=100),
        Event(source=Source.DZ_FEED, t_arrival_ns=t_ns, market=MKT, kind=Kind.QUOTE,
              side=Side.ASK, price=ask, size=100),
    ]


def print_trade(price: float, size: float, t_ns: int, side: Side = Side.BUY) -> Event:
    return Event(source=Source.DZ_FEED, t_arrival_ns=t_ns, market=MKT, kind=Kind.TRADE,
                 side=side, price=price, size=size, exch_ts_ns=t_ns - 1000)


def feed(bot: FollowThePrint, events: list[Event]):
    last = None
    for event in events:
        last = bot.on_event(event) or last
    return last


def test_big_buy_print_lifts_a_stale_ask():
    bot = FollowThePrint(StrategyConfig(min_print_size=50))
    feed(bot, quote(100.0, 100.5, 1_000))
    intent = bot.on_event(print_trade(100.5, 200, 2_000))
    assert intent is not None
    assert intent.side is Side.BUY
    assert intent.limit_price == 100.5
    assert intent.t_decided_ns == 2_000
    assert intent.trigger_exch_ts_ns == 1_000


def test_small_print_is_ignored():
    bot = FollowThePrint(StrategyConfig(min_print_size=50))
    feed(bot, quote(100.0, 100.5, 1_000))
    assert bot.on_event(print_trade(100.5, 10, 2_000)) is None


def test_ask_already_above_the_print_is_not_stale():
    """The quote moved with the print, so there is nothing left to take and
    speed would buy nothing. The rule must stay out."""
    bot = FollowThePrint(StrategyConfig(min_print_size=50))
    feed(bot, quote(100.0, 101.0, 1_000))
    assert bot.on_event(print_trade(100.5, 200, 2_000)) is None


def test_sell_print_hits_a_stale_bid():
    bot = FollowThePrint(StrategyConfig(min_print_size=50))
    feed(bot, quote(100.0, 100.5, 1_000))
    intent = bot.on_event(print_trade(100.0, 200, 2_000, side=Side.SELL))
    assert intent is not None and intent.side is Side.SELL and intent.limit_price == 100.0


def test_cooldown_blocks_the_next_print():
    bot = FollowThePrint(StrategyConfig(min_print_size=50, cooldown_ns=5_000))
    feed(bot, quote(100.0, 100.5, 1_000))
    assert bot.on_event(print_trade(100.5, 200, 2_000)) is not None
    assert bot.on_event(print_trade(100.5, 200, 4_000)) is None, "inside cooldown"
    assert bot.on_event(print_trade(100.5, 200, 9_000)) is not None, "cooldown expired"


def test_position_cap_stops_accumulating():
    bot = FollowThePrint(StrategyConfig(min_print_size=50, cooldown_ns=0,
                                        order_size=1, max_position=2))
    feed(bot, quote(100.0, 100.5, 1_000))
    fired = [bot.on_event(print_trade(100.5, 200, 2_000 + i)) for i in range(4)]
    assert sum(1 for f in fired if f is not None) == 2
    assert bot.position(MKT) == 2
