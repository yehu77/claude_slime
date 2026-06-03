from formatter import greet, format_score


def test_greet():
    assert greet("Alice") == "Hello, Alice!"


def test_greet_bob():
    assert greet("Bob") == "Hello, Bob!"


def test_format_score():
    assert format_score("Alice", 100) == "Alice scored 100 points"
