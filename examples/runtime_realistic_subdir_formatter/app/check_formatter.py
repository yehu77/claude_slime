from formatter import title_line


def main() -> None:
    assert title_line("claude") == "== Claude =="


if __name__ == "__main__":
    main()
