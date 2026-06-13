from typing import get_type_hints

from tracking import build_tracking_code


def test_build_tracking_code_output():
    assert build_tracking_code("ORD", 7) == "ORD-7"


def test_build_tracking_code_annotations():
    assert get_type_hints(build_tracking_code) == {
        "order_id": str,
        "suffix": int,
        "return": str,
    }
