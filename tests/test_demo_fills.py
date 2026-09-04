"""The whole demo rests on this file: a later decision must lose the quote.

If these pass while the fill model is wrong, the stream shows a lie, so each
test asserts the behaviour that would break, not the constants that produce it.
"""
from common.event import Side
from demo.book import TopOfBook
from demo.fills import GroundTruth, Scoreboard
from demo.strategy import Intent

MKT = "KXBTCPERP"
MS = 1_000_000


def book(t_ns: int, bid: float, ask: float) -> TopOfBook:
    return TopOfBook(market=MKT, bid=bid, bid_size=50, ask=ask, ask_size=50,
                     t_updated_ns=t_ns)


def buy_intent(t_ns: int, limit: float = 100.5) -> Intent:
    return Intent(market=MKT, side=Side.BUY, limit_price=limit, size=1,
                  t_decided_ns=t_ns, trigger_price=limit, trigger_size=200,
                  trigger_exch_ts_ns=t_ns)


def test_the_seven_millisecond_story():
    """Same trigger, two bots. The ask is pulled 3 ms after the print. The bot
    that decided at the print fills; the bot that decided 7 ms later does not."""
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(3 * MS, 100.0, 101.0))  # ask pulled

    fast = truth.settle(buy_intent(0))
    slow = truth.settle(buy_intent(7 * MS))

    assert fast.filled and fast.price == 100.5
    assert not slow.filled and slow.reason == "quote_gone"


def test_a_slower_bot_still_fills_when_nothing_moved():
    """Speed must not be rewarded when it changed nothing. A quiet market has to
    show both bots filling, or the demo is rigged."""
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))

    assert truth.settle(buy_intent(0)).filled
    assert truth.settle(buy_intent(50 * MS)).filled


def test_fill_uses_the_shared_book_not_the_bot_limit():
    """If the market improved, we pay the better price, not our stale limit."""
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.2))
    assert truth.settle(buy_intent(0, limit=100.5)).price == 100.2


def test_markout_is_positive_when_the_market_runs_our_way():
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(500 * MS, 102.0, 102.5))
    fill = truth.settle(buy_intent(0), markout_ns=1_000 * MS)
    assert fill.markout is not None and fill.markout > 0

    truth_down = GroundTruth()
    truth_down.record(book(0, 100.0, 100.5))
    truth_down.record(book(500 * MS, 98.0, 98.5))
    assert truth_down.settle(buy_intent(0), markout_ns=1_000 * MS).markout < 0


def test_sell_side_mirrors_the_buy_side():
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(3 * MS, 99.0, 100.5))  # bid pulled down
    sell = Intent(market=MKT, side=Side.SELL, limit_price=100.0, size=1,
                  t_decided_ns=7 * MS, trigger_price=100.0, trigger_size=200,
                  trigger_exch_ts_ns=0)
    assert not truth.settle(sell).filled


def test_state_at_never_looks_into_the_future():
    truth = GroundTruth()
    truth.record(book(10 * MS, 100.0, 100.5))
    assert truth.state_at(MKT, 5 * MS) is None, "a decision cannot use a later book"
    assert truth.state_at(MKT, 10 * MS) is not None


def test_unknown_market_is_a_miss_not_a_crash():
    assert GroundTruth().settle(buy_intent(0)).reason == "no_book"


def test_scoreboard_counts_what_it_says():
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(3 * MS, 100.0, 101.0))
    board = Scoreboard("dz")
    board.add(truth.settle(buy_intent(0)))
    board.add(truth.settle(buy_intent(7 * MS)))
    assert board.intents == 2 and board.fills == 1 and board.missed == 1
    assert board.as_dict()["fill_rate"] == 50.0


def test_reaction_time_means_a_bot_can_lose_the_quote_it_just_saw():
    """Without a reaction delay the fastest bot is judged on the very snapshot it
    acted on and fills every time, which is a structural 100% that measures
    nothing. The quote here is pulled 2 ms after the decision."""
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(2 * MS, 100.0, 101.0))

    assert truth.settle(buy_intent(0), reaction_ns=0).filled
    assert not truth.settle(buy_intent(0), reaction_ns=5 * MS).filled


def test_reaction_time_does_not_change_the_gap_between_the_two_bots():
    """It is applied to both bots, so it must shift them together, never tilt
    the comparison."""
    truth = GroundTruth()
    truth.record(book(0, 100.0, 100.5))
    truth.record(book(4 * MS, 100.0, 101.0))
    reaction = 1 * MS
    assert truth.settle(buy_intent(0), reaction_ns=reaction).filled
    assert not truth.settle(buy_intent(7 * MS), reaction_ns=reaction).filled
