from akashik.identity import content_hash, normalize, normalized_hash


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize("  Hello\tWORLD\n\nAgain  ") == "hello world again"
    assert normalize("Hello,   World!") == "hello, world!"


def test_content_hash_is_stable_and_case_sensitive() -> None:
    assert content_hash("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert content_hash("abc") != content_hash("ABC")


def test_normalized_hash_matches_case_and_whitespace_variants() -> None:
    first = normalized_hash("A  local\tLibrary")
    second = normalized_hash("a local library")
    assert first == second
    assert first != content_hash("A  local\tLibrary")
