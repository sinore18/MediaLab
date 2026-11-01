import pytest

from server.domain.schemas import AlignedWord
from server.services.processing.pii_detector import (
    PiiDetector,
    validate_aadhaar,
    validate_card,
    validate_ifsc,
    validate_luhn,
    validate_mobile,
    validate_otp,
    validate_pan,
    validate_verhoeff,
)


def _words(
    tokens: list[str], pause_before: dict[int, float] | None = None
) -> list[AlignedWord]:
    pause_before = pause_before or {}
    words = []
    current_time = 0.0
    for index, token in enumerate(tokens):
        current_time += pause_before.get(index, 0.0)
        words.append(
            AlignedWord(word=token, start=current_time, end=current_time + 0.08)
        )
        current_time += 0.1
    return words


def _with_luhn_check_digit(prefix: str) -> str:
    for digit in "0123456789":
        candidate = prefix + digit
        if validate_luhn(candidate):
            return candidate
    raise AssertionError("A Luhn check digit must exist.")


def _with_verhoeff_check_digit(prefix: str) -> str:
    for digit in "0123456789":
        candidate = prefix + digit
        if validate_verhoeff(candidate):
            return candidate
    raise AssertionError("A Verhoeff check digit must exist.")


@pytest.mark.parametrize(
    ("validator", "valid", "invalid"),
    [
        (validate_luhn, "79927398713", "79927398714"),
        (validate_card, "7992739871300", "7992739871301"),
        (validate_verhoeff, "236", "237"),
        (validate_aadhaar, _with_verhoeff_check_digit("23456789012"), "134567890123"),
        (validate_pan, "ABCDE1234F", "ABCD1234F"),
        (validate_ifsc, "ABCD0EF1234", "ABCD1EF1234"),
        (validate_mobile, "9876543210", "5876543210"),
        (validate_otp, "123456", "123"),
    ],
)
def test_pii_validators(validator, valid: str, invalid: str) -> None:
    assert validator(valid)
    assert not validator(invalid)


def test_detector_finds_card_with_source_word_indexes() -> None:
    value = _with_luhn_check_digit("7992739871300")
    words = _words(list(value))

    spans = PiiDetector().detect(words)

    assert len(spans) == 1
    assert spans[0].category == "CARD"
    assert (spans[0].first_word_idx, spans[0].last_word_idx) == (0, len(value) - 1)
    assert (spans[0].start, spans[0].end) == (words[0].start, words[-1].end)
    assert spans[0].validator_result is True
    assert value not in str(spans[0].model_dump())


def test_detector_finds_aadhaar_mobile_pan_and_ifsc() -> None:
    aadhaar = _with_verhoeff_check_digit("23456789012")
    cases = [
        ("AADHAAR", list(aadhaar)),
        ("MOBILE", list("9876543210")),
        ("PAN", list("ABCDE1234F")),
        ("IFSC", list("ABCD0EF1234")),
    ]

    for category, tokens in cases:
        spans = PiiDetector().detect(_words(tokens))
        assert [span.category for span in spans] == [category]


def test_detector_finds_otp_with_cue_across_a_short_pause() -> None:
    words = _words(
        ["your", "OTP", "is", "one", "two", "three", "four"],
        pause_before={5: 0.6},
    )

    spans = PiiDetector().detect(words)

    assert len(spans) == 1
    assert spans[0].category == "OTP"
    assert (spans[0].first_word_idx, spans[0].last_word_idx) == (3, 6)


def test_detector_finds_otp_with_hindi_cue_and_numeric_token() -> None:
    words = _words(["हाँ", "ओटीपी", "है", "482915।"])

    spans = PiiDetector().detect(words)

    assert len(spans) == 1
    assert spans[0].category == "OTP"
    assert (spans[0].first_word_idx, spans[0].last_word_idx) == (3, 3)


def test_detector_splits_long_pause_and_corrects_no_wait_digit() -> None:
    tokens = [
        "nine",
        "eight",
        "seven",
        "six",
        "five",
        "four",
        "three",
        "two",
        "one",
        "five",
        "no",
        "wait",
        "zero",
    ]
    words = _words(tokens)
    spans = PiiDetector().detect(words)

    assert [span.category for span in spans] == ["MOBILE"]
    assert (spans[0].first_word_idx, spans[0].last_word_idx) == (0, 12)

    split_words = _words(["OTP", "one", "two", "three", "four"], pause_before={3: 1.3})
    assert PiiDetector().detect(split_words) == []


def test_detector_rejects_invalid_checksum_candidates() -> None:
    invalid_card = "7992739871301"
    invalid_aadhaar = "134567890123"

    assert all(
        span.category != "CARD"
        for span in PiiDetector().detect(_words(list(invalid_card)))
    )
    assert PiiDetector().detect(_words(list(invalid_aadhaar))) == []
