from counter import count_up_to, inclusive_count


def test_count_up_to():
    assert count_up_to(3) == [0, 1, 2]


def test_inclusive_count():
    assert inclusive_count(3) == [0, 1, 2, 3]


def test_inclusive_count_zero():
    assert inclusive_count(0) == [0]
