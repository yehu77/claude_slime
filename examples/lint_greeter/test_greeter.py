from pathlib import Path

from greeter import greet


def test_greet_output():
    assert greet("Ada") == "Hello, Ada"


def test_debug_print_removed():
    source = Path(__file__).with_name("greeter.py").read_text(encoding="utf-8")
    assert "print(" not in source


def test_unused_import_removed():
    source = Path(__file__).with_name("greeter.py").read_text(encoding="utf-8")
    assert "import math" not in source
