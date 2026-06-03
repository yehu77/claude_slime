from comparator import max_of, min_of


def test_max_of():
    assert max_of(3, 5) == 5


def test_max_of_reverse():
    assert max_of(7, 2) == 7


def test_max_of_equal():
    assert max_of(4, 4) == 4


def test_min_of():
    assert min_of(3, 5) == 3


def test_min_of_reverse():
    assert min_of(7, 2) == 2
