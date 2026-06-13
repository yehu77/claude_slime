from pathlib import Path

from banner import make_banner


def test_make_banner_output():
    assert make_banner("Ada") == "*** Ada ***"


def test_banner_uses_spaces_for_indentation():
    source = Path(__file__).with_name("banner.py").read_text(encoding="utf-8")
    assert "\t" not in source
