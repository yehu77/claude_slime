from labels import build_label


def test_build_label_default_behavior():
    assert build_label("item") == "item"


def test_build_label_supports_prefix():
    assert build_label("item", prefix="ID") == "ID:item"
