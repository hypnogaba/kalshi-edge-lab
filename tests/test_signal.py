from bot.signal import Decision, SignalConfig, decide

CFG = SignalConfig(entry_dollars=50.0, max_yes_cents=90, min_yes_cents=10)


def test_hold_on_bucket_market():
    assert decide(strike=68000, is_threshold=False, kalshi_yes_cents=50, spot=69000, cfg=CFG) == Decision.HOLD


def test_buy_yes_when_spot_well_above_strike_and_not_priced_in():
    # spot far above strike -> "yes" likely; market yes price still cheap -> underpriced -> BUY_YES
    assert decide(strike=68000, is_threshold=True, kalshi_yes_cents=60, spot=69000, cfg=CFG) == Decision.BUY_YES


def test_hold_when_already_priced_in():
    # spot above strike but market already near-certain (yes >= max) -> no edge
    assert decide(strike=68000, is_threshold=True, kalshi_yes_cents=95, spot=69000, cfg=CFG) == Decision.HOLD


def test_buy_no_when_spot_well_below_strike_and_yes_still_expensive():
    assert decide(strike=70000, is_threshold=True, kalshi_yes_cents=40, spot=69000, cfg=CFG) == Decision.BUY_NO


def test_hold_inside_entry_band():
    # spot within entry_dollars of strike -> too close to call -> HOLD
    assert decide(strike=69000, is_threshold=True, kalshi_yes_cents=50, spot=69010, cfg=CFG) == Decision.HOLD
