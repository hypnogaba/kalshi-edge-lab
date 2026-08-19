from common.event import Event, Source, Kind, Side


def test_event_construction_and_immutability():
    e = Event(source=Source.KALSHI_WS, t_arrival_ns=123, market="BTC",
              kind=Kind.TRADE, price=52, size=10, side=Side.YES, seq=7)
    assert e.source == "kalshi_ws"
    assert e.kind == "trade"
    assert e.price == 52 and e.size == 10 and e.side == "yes" and e.seq == 7
    try:
        e.price = 99  # frozen
        assert False, "Event should be immutable"
    except AttributeError:
        pass


def test_event_optional_fields_default_none():
    e = Event(source=Source.DZ_FEED, t_arrival_ns=1, market="BTC", kind=Kind.BOOK_SNAPSHOT)
    assert e.price is None and e.size is None and e.side is None and e.seq is None
