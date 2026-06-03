from typing import get_type_hints

from repeat import repeat_text


def test_repeat_text_output():
    assert repeat_text("ha", 3) == "hahaha"


def test_repeat_text_annotations():
    assert get_type_hints(repeat_text) == {
        "text": str,
        "times": int,
        "return": str,
    }
