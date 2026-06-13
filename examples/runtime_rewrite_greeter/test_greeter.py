from greeter import render_greeting


def test_render_greeting_includes_name():
    assert render_greeting("Ada") == "Hello, Ada!"


def test_render_greeting_keeps_punctuation():
    assert render_greeting("Lin") == "Hello, Lin!"
