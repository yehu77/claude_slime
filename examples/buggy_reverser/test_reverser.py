from reverser import reverse_string, reverse_words


def test_reverse_string():
    assert reverse_string("hello") == "olleh"


def test_reverse_string_empty():
    assert reverse_string("") == ""


def test_reverse_words():
    assert reverse_words("hello world") == "world hello"


def test_reverse_words_three():
    assert reverse_words("a b c") == "c b a"
