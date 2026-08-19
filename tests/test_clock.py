from common.clock import now_ns


def test_now_ns_is_int_and_nondecreasing():
    a = now_ns()
    b = now_ns()
    assert isinstance(a, int)
    assert b >= a
    assert a > 0
