"""Publisher-arm arbitration: take one arm's copy of the feed, not both."""
from sources.dz_feed.arms import ArmArbiter

MS = 1_000_000
FAST, SLOW = 101, 1


def _race(arb: ArmArbiter, n: int, start_ns: int = 0, lead_ms: float = 5.0,
          fast: int = FAST, slow: int = SLOW) -> int:
    """Feed `n` trades down both arms, `fast` arriving `lead_ms` earlier.

    Calls are in the reader's own order -- note, observe, then ask -- so the
    counters this produces are the ones a live reader would produce."""
    t = start_ns
    for i in range(n):
        key = ("KXBTCPERP", 80000.0 + i, 1.0)
        for channel, at in ((fast, t), (slow, t + int(lead_ms * MS))):
            arb.note_frame(channel, at)
            arb.observe_trade(channel, key, at)
            arb.accepts(channel, at)
        t += 100 * MS
    return t


def test_it_takes_no_side_until_it_has_watched_a_race():
    """Warm-up must not drop anything: a wrong guess would be a hole in the
    feed, and taking both is only what the reader already did."""
    arb = ArmArbiter()
    assert arb.selected is None
    assert arb.accepts(FAST, 0) and arb.accepts(SLOW, 0)


def test_it_selects_the_arm_that_arrives_first():
    arb = ArmArbiter()
    now = _race(arb, 20)
    assert arb.selected == FAST
    assert arb.accepts(FAST, now)
    assert not arb.accepts(SLOW, now)


def test_the_choice_comes_from_the_data_not_from_the_channel_number():
    """If DoubleZero swapped which channel leads, a hard-coded number would
    quietly start measuring the slow arm. The lower channel id wins here only
    because it is the one that arrives first."""
    arb = ArmArbiter()
    now = _race(arb, 20, fast=SLOW, slow=FAST)
    assert arb.selected == SLOW
    assert not arb.accepts(FAST, now)


def test_one_arm_alone_is_never_dropped():
    """A single-arm group must pass straight through: there is nothing to
    arbitrate, and pinning to a channel that does not exist is silence."""
    arb = ArmArbiter()
    t = 0
    for i in range(200):
        arb.note_frame(FAST, t)
        arb.observe_trade(FAST, ("KXBTCPERP", 80000.0 + i, 1.0), t)
        assert arb.accepts(FAST, t)
        t += MS
    assert arb.selected is None


def test_the_same_arm_repeating_a_key_does_not_count_as_a_race():
    """Two identical prints on one arm are two trades, not two copies of one.
    Counting them would let a single busy arm 'beat' itself."""
    arb = ArmArbiter()
    t = 0
    for _ in range(40):
        arb.note_frame(FAST, t)
        arb.observe_trade(FAST, ("KXBTCPERP", 80000.0, 1.0), t)
        t += MS
    assert arb.selected is None


def test_a_selected_arm_that_goes_silent_releases_the_selection():
    """Otherwise retiring a publisher would take the whole feed down with it."""
    arb = ArmArbiter(silence_ns=2_000_000_000)
    now = _race(arb, 20)
    assert arb.selected == FAST
    later = now + 3_000_000_000
    assert arb.accepts(SLOW, later)      # the pin is released, not enforced
    assert arb.selected is None


def test_a_forced_channel_overrides_the_arbitration():
    arb = ArmArbiter(SLOW)
    now = _race(arb, 20)
    assert arb.selected == SLOW
    assert arb.accepts(SLOW, now)
    assert not arb.accepts(FAST, now)
    assert arb.stats()["mode"] == "forced"


def test_it_publishes_what_the_choice_rests_on():
    arb = ArmArbiter()
    now = _race(arb, 20, lead_ms=5.0)
    st = arb.stats(now)
    assert st["mode"] == "auto"
    assert st["selected"] == FAST
    assert st["pairs"] == 20
    assert st["channels"][str(FAST)]["wins"] == 20
    assert st["channels"][str(SLOW)]["wins"] == 0
    assert st["channels"][str(SLOW)]["dropped_frames"] >= 1
    # the cost of the arm we dropped, as its own number
    assert st["loser_lag_ms"]["p50"] == 5.0


def test_pending_sightings_do_not_grow_without_bound():
    """Half the prints never get a twin. Holding them forever would be a leak
    in a process that runs for days."""
    arb = ArmArbiter(pair_ttl_ns=1_000_000)
    t = 0
    for i in range(5000):
        arb.note_frame(FAST, t)
        arb.observe_trade(FAST, ("KXBTCPERP", float(i), 1.0), t)
        t += MS
    assert len(arb._pending) < 1000
