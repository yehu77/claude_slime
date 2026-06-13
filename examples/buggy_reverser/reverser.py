def reverse_string(s: str) -> str:
    return s[::-1]


def reverse_words(sentence: str) -> str:
    return " ".join(sentence.split(" ")[::1])
