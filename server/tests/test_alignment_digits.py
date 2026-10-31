import time

from server.services.processing.alignment_text import fill_unaligned, spoken_pieces
from server.services.processing.local_aligner import LocalMMSWordAligner


class FakeRomanizer:
    """Stand-in for uroman: every non-ASCII piece becomes one ascii word."""

    def romanize_string(self, text, lcode=None):
        return "xx" if not text.isascii() else text


def test_long_digit_token_english():
    pieces = spoken_pieces("424242424242", "en-IN")
    assert len(pieces) == 12 and pieces[:4] == ["four", "two", "four", "two"]


def test_devanagari_digits_and_hindi_table():
    assert spoken_pieces("४२", "hi-IN") == ["चार", "दो"]
    assert spoken_pieces("42", "hi-IN") == ["चार", "दो"]


def test_mixed_alnum_pan():
    assert spoken_pieces("GCPPA7536G", "en") == [
        "gee", "see", "pee", "pee", "ay", "seven", "five", "three", "six", "gee"]


def test_plain_words_unchanged_and_acronym_spelled():
    assert spoken_pieces("hello", "en") == ["hello"]
    assert spoken_pieces("नमस्ते", "hi") == ["नमस्ते"]
    assert spoken_pieces("OTP", "en") == ["oh", "tee", "pee"]


def test_digits_attached_to_native_word():
    assert spoken_pieces("50रुपये", "hi") == ["पाँच", "शून्य", "रुपये"]


def test_fill_unaligned_between_neighbours():
    aligned = {0: (0.0, 1.0), 3: (2.0, 3.0)}
    out = fill_unaligned(aligned, {1, 2}, 4.0)
    assert out[1] == (1.0, 1.5) and out[2] == (1.5, 2.0)


def test_fill_unaligned_edges():
    assert fill_unaligned({1: (1.0, 2.0)}, {0}, 4.0)[0] == (0.0, 1.0)
    assert fill_unaligned({0: (0.0, 1.0)}, {1}, 4.0)[1] == (1.0, 4.0)


def test_fill_unaligned_never_zero_width():
    out = fill_unaligned({0: (0.0, 1.0), 2: (1.0, 2.0)}, {1}, 3.0)
    assert out[1][1] > out[1][0]


def test_digit_token_no_longer_fails_normalization():
    aligner = LocalMMSWordAligner(language="en-IN")
    words = aligner._romanize_word("424242424242", FakeRomanizer())
    assert len(words) == 12 and all(w.isascii() for w in words)


def test_hindi_digit_token_goes_through_romanizer():
    aligner = LocalMMSWordAligner(language="hi-IN")
    assert aligner._romanize_word("4242", FakeRomanizer()) == ["xx"] * 4


def test_romanization_language_mapping():
    assert LocalMMSWordAligner(language="bn-IN")._romanization_language() == "ben"
    assert LocalMMSWordAligner(language="en")._romanization_language() == "eng"


def test_expansion_is_fast():
    words = ["424242424242", "GCPPA7536G", "नमस्ते", "hello"] * 50
    start = time.perf_counter()
    for w in words:
        spoken_pieces(w, "en")
    assert time.perf_counter() - start < 0.05