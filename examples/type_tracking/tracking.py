def build_tracking_code(order_id: str, suffix: str) -> list[str]:
    return f"{order_id}-{suffix}"
