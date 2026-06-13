def filter_positive(numbers: list[int]) -> list[int]:
    return [n for n in numbers if n > 0 or n == 0]


def filter_negative(numbers: list[int]) -> list[int]:
    return [n for n in numbers if n < 0]
