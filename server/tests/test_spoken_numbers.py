import pytest

from server.domain.schemas import AlignedWord
from server.services.processing.spoken_numbers import (
    NormalizedCharacter,
    normalize_spoken_tokens,
)


def aligned_words(*values: str) -> list[AlignedWord]:
    return [
        AlignedWord(word=value, start=index * 0.1, end=(index + 1) * 0.1)
        for index, value in enumerate(values)
    ]


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (
            (
                "zero",
                "oh",
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
            ),
            "00123456789",
        ),
        (
            (
                "ek",
                "do",
                "teen",
                "char",
                "paanch",
                "chhe",
                "saat",
                "aath",
                "nau",
                "shunya",
            ),
            "1234567890",
        ),
        (("०", "१", "२", "३", "४", "५", "६", "७", "८", "९"), "0123456789"),
        (
            ("एक", "दो", "तीन", "चार", "पांच", "छह", "सात", "आठ", "नौ", "शून्य"),
            "1234567890",
        ),
    ],
)
def test_normalizes_digit_words_and_numerals(
    words: tuple[str, ...], expected: str
) -> None:
    result = normalize_spoken_tokens(aligned_words(*words))

    assert "".join(character.value for character in result) == expected


@pytest.mark.parametrize(
    ("cue", "digit", "expected"),
    [("double", "five", "55"), ("triple", "०", "000")],
)
def test_repetition_maps_output_to_spoken_digit_word(
    cue: str, digit: str, expected: str
) -> None:
    result = normalize_spoken_tokens(aligned_words(cue, digit))

    assert [character.value for character in result] == list(expected)
    assert {character.word_index for character in result} == {1}


def test_spelled_letters_and_phonetic_names_keep_source_indexes() -> None:
    result = normalize_spoken_tokens(
        aligned_words("A", "for", "Apple", "bee", "cee", "123")
    )

    assert result == [
        NormalizedCharacter(value="A", word_index=0),
        NormalizedCharacter(value="B", word_index=3),
        NormalizedCharacter(value="C", word_index=4),
        NormalizedCharacter(value="1", word_index=5),
        NormalizedCharacter(value="2", word_index=5),
        NormalizedCharacter(value="3", word_index=5),
    ]
