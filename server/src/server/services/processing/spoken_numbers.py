import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from server.domain.schemas import AlignedWord

_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "ek": "1",
    "एक": "1",
    "two": "2",
    "do": "2",
    "दो": "2",
    "three": "3",
    "teen": "3",
    "tin": "3",
    "तीन": "3",
    "four": "4",
    "char": "4",
    "chaar": "4",
    "चार": "4",
    "five": "5",
    "paanch": "5",
    "panch": "5",
    "पाँच": "5",
    "पांच": "5",
    "six": "6",
    "chhe": "6",
    "chhah": "6",
    "छह": "6",
    "छः": "6",
    "seven": "7",
    "saat": "7",
    "सात": "7",
    "eight": "8",
    "aath": "8",
    "आठ": "8",
    "nine": "9",
    "nau": "9",
    "नौ": "9",
    "shunya": "0",
    "shoonya": "0",
    "शून्य": "0",
}

_LETTER_NAMES = {
    "ay": "A",
    "bee": "B",
    "bi": "B",
    "cee": "C",
    "see": "C",
    "dee": "D",
    "ee": "E",
    "ef": "F",
    "eff": "F",
    "gee": "G",
    "aitch": "H",
    "haitch": "H",
    "eye": "I",
    "jay": "J",
    "kay": "K",
    "el": "L",
    "em": "M",
    "en": "N",
    "pee": "P",
    "cue": "Q",
    "ar": "R",
    "ess": "S",
    "tee": "T",
    "you": "U",
    "vee": "V",
    "double-u": "W",
    "ex": "X",
    "why": "Y",
    "zee": "Z",
    "zed": "Z",
}


@dataclass(frozen=True)
class NormalizedCharacter:
    """A normalized digit or letter and its originating aligned-word index."""

    value: str
    word_index: int


def normalize_spoken_tokens(words: Sequence[AlignedWord]) -> list[NormalizedCharacter]:
    """Normalize digit words, numeral glyphs, repetitions, and spelled letters."""
    normalized: list[NormalizedCharacter] = []
    index = 0
    while index < len(words):
        token = _clean_token(words[index].word)

        if token in {"double", "triple"} and index + 1 < len(words):
            repeated_token = _clean_token(words[index + 1].word)
            repeated = _token_characters(repeated_token)
            if repeated and all(character.isdigit() for character in repeated):
                count = 2 if token == "double" else 3
                normalized.extend(
                    NormalizedCharacter(character, index + 1)
                    for _ in range(count)
                    for character in repeated
                )
                index += 2
                continue

        characters = _token_characters(token)
        if characters:
            normalized.extend(
                NormalizedCharacter(character, index) for character in characters
            )
        elif len(token) == 1 and token.isascii() and token.isalpha():
            normalized.append(NormalizedCharacter(token.upper(), index))
            if index + 2 < len(words) and _clean_token(words[index + 1].word) == "for":
                index += 2
        elif token in _LETTER_NAMES:
            normalized.append(NormalizedCharacter(_LETTER_NAMES[token], index))
        index += 1

    return normalized


def _clean_token(token: str) -> str:
    """Normalize case and remove surrounding punctuation from one aligned word."""
    cleaned = unicodedata.normalize("NFC", token).casefold()
    start = 0
    end = len(cleaned)
    while start < end and unicodedata.category(cleaned[start])[0] in {"P", "S"}:
        start += 1
    while start < end and unicodedata.category(cleaned[end - 1])[0] in {"P", "S"}:
        end -= 1
    return cleaned[start:end]


def _token_characters(token: str) -> str:
    """Return digits represented by a numeral token or a supported spoken digit."""
    if token in _DIGIT_WORDS:
        return _DIGIT_WORDS[token]
    if not token:
        return ""
    try:
        digits = "".join(str(unicodedata.digit(character)) for character in token)
    except (TypeError, ValueError):
        return ""
    return digits if all(character.isdigit() for character in token) else ""
