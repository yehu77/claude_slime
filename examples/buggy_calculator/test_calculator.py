from calculator import add


def test_add():
    assert add(1, 2) == 3


def test_add_zero():
    assert add(5, 0) == 5
