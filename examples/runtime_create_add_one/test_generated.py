from generated import add_one


def test_add_one_handles_positive_values():
    assert add_one(1) == 2


def test_add_one_handles_negative_values():
    assert add_one(-1) == 0
