from calculator import divide, integer_divide


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_fraction():
    assert divide(7, 2) == 3.5


def test_integer_divide():
    assert integer_divide(7, 2) == 3


def test_integer_divide_exact():
    assert integer_divide(10, 5) == 2
