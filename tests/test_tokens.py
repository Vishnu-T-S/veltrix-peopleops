from app.tokens import _VENDOR_FILE, count_tokens, using_exact_counts


def test_vocabulary_is_vendored_so_counting_never_needs_the_network():
    assert _VENDOR_FILE.exists()


def test_counts_use_the_exact_cl100k_base_encoding():
    assert using_exact_counts()
    assert count_tokens("hello world") == 2        # known cl100k_base result: [15339, 1917]
    assert count_tokens("How many sick days do I get?") == 8


def test_empty_text_is_zero_tokens():
    assert count_tokens("") == 0
    assert count_tokens(None) == 0


def test_text_that_looks_like_a_special_token_is_counted_not_rejected():
    assert count_tokens("hello <|endoftext|> world") > 2
