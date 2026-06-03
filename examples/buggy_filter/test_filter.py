from filter import filter_positive, filter_negative


def test_filter_positive():
    assert filter_positive([1, -2, 3, 0, -5]) == [1, 3]


def test_filter_positive_all_negative():
    assert filter_positive([-1, -2, -3]) == []


def test_filter_negative():
    assert filter_negative([1, -2, 3, 0, -5]) == [-2, -5]
