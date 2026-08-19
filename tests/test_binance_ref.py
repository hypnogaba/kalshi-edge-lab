from reference.binance_ws import parse_mid


def test_parse_mid():
    assert parse_mid('{"u":1,"s":"BTCUSDT","b":"68000.0","B":"1","a":"68002.0","A":"2"}') == 68001.0


def test_parse_mid_ignores_non_ticker():
    assert parse_mid('{"result":null,"id":1}') is None
