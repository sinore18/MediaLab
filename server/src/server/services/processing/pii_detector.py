import re
import unicodedata
from collections.abc import Callable, Sequence

from server.domain.schemas import AlignedWord, DetectionSpan
from server.services.processing.spoken_numbers import (
    NormalizedCharacter,
    normalize_spoken_tokens,
)

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)
_OTP_CUES = {
    "code",
    "otp",
    "passcode",
    "password",
    "pin",
    "verification",
}
_JOIN_WORDS = {"and", "then", "uh", "um"}
_CORRECTION_PHRASES = (("no", "wait"), ("wait",), ("sorry",), ("i", "mean"))


def validate_luhn(value: str) -> bool:
    """Return whether a decimal string has a valid Luhn checksum."""
    if not value.isascii() or not value.isdigit():
        return False
    total = 0
    for index, character in enumerate(reversed(value)):
        digit = int(character)
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card(value: str) -> bool:
    """Validate a 13-19 digit payment-card candidate using Luhn."""
    return 13 <= len(value) <= 19 and validate_luhn(value)


def validate_verhoeff(value: str) -> bool:
    """Return whether a decimal string has a valid Verhoeff checksum."""
    if not value.isascii() or not value.isdigit():
        return False
    checksum = 0
    for index, character in enumerate(reversed(value)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[index % 8][int(character)]]
    return checksum == 0


def validate_aadhaar(value: str) -> bool:
    """Validate a 12-digit Aadhaar-shaped candidate using Verhoeff."""
    return (
        len(value) == 12
        and value.isascii()
        and value.isdigit()
        and value[0] in "23456789"
        and validate_verhoeff(value)
    )


def validate_pan(value: str) -> bool:
    """Validate the structural PAN pattern without checking identity data."""
    return re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value) is not None


def validate_ifsc(value: str) -> bool:
    """Validate the structural IFSC pattern."""
    return re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", value) is not None


def validate_mobile(value: str) -> bool:
    """Validate a 10-digit Indian mobile-number shape."""
    return re.fullmatch(r"[6-9][0-9]{9}", value) is not None


def validate_otp(value: str) -> bool:
    """Validate the length and digits of an OTP candidate."""
    return value.isascii() and value.isdigit() and 4 <= len(value) <= 8


class PiiDetector:
    """Detect validated spoken financial identifiers from aligned words."""

    def __init__(self, maximum_pause_seconds: float = 1.2) -> None:
        if maximum_pause_seconds < 0:
            raise ValueError("maximum_pause_seconds must not be negative.")
        self.maximum_pause_seconds = maximum_pause_seconds

    def detect(self, words: Sequence[AlignedWord]) -> list[DetectionSpan]:
        """Find PII spans and map every candidate back to aligned-word times."""
        normalized = normalize_spoken_tokens(words)
        segments = self._segments(normalized, words)
        matches: list[DetectionSpan] = []
        for segment in segments:
            matches.extend(self._detect_digit_runs(segment, words))
            matches.extend(self._detect_alphanumeric(segment, words))
        return sorted(
            matches, key=lambda match: (match.start, match.end, match.category)
        )

    def _segments(
        self,
        normalized: Sequence[NormalizedCharacter],
        words: Sequence[AlignedWord],
    ) -> list[list[NormalizedCharacter]]:
        segments: list[list[NormalizedCharacter]] = []
        current: list[NormalizedCharacter] = []
        for character in normalized:
            if current:
                previous = current[-1]
                if character.word_index != previous.word_index:
                    skipped = words[previous.word_index + 1 : character.word_index]
                    skipped_tokens = [_clean_token(word.word) for word in skipped]
                    correction = _contains_correction(skipped_tokens)
                    if correction:
                        while current and current[-1].word_index == previous.word_index:
                            current.pop()
                    elif words[character.word_index].start - words[
                        previous.word_index
                    ].end > self.maximum_pause_seconds or not _may_join(skipped_tokens):
                        segments.append(current)
                        current = []
            current.append(character)
        if current:
            segments.append(current)
        return [segment for segment in segments if segment]

    def _detect_digit_runs(
        self,
        segment: Sequence[NormalizedCharacter],
        words: Sequence[AlignedWord],
    ) -> list[DetectionSpan]:
        matches: list[DetectionSpan] = []
        index = 0
        while index < len(segment):
            if not segment[index].value.isdigit():
                index += 1
                continue
            end = index
            while end < len(segment) and segment[end].value.isdigit():
                end += 1
            run = segment[index:end]
            card = self._find_card(run, words)
            if card is not None:
                matches.append(card)
            else:
                aadhaar = self._find_valid_window(run, 12, validate_aadhaar)
                mobile = self._find_valid_window(run, 10, validate_mobile)
                if aadhaar is not None:
                    matches.append(self._span("AADHAAR", aadhaar, words, 0.99))
                elif mobile is not None:
                    matches.append(self._span("MOBILE", mobile, words, 0.98))
                else:
                    otp = self._find_otp(run, words)
                    if otp is not None:
                        matches.append(self._span("OTP", otp, words, 0.9))
            index = end
        return matches

    def _find_card(
        self,
        run: Sequence[NormalizedCharacter],
        words: Sequence[AlignedWord],
    ) -> DetectionSpan | None:
        for length in range(min(19, len(run)), 12, -1):
            for start in range(len(run) - length + 1):
                candidate = run[start : start + length]
                value = "".join(character.value for character in candidate)
                if validate_card(value):
                    return self._span("CARD", candidate, words, 0.99)
        return None

    @staticmethod
    def _find_valid_window(
        run: Sequence[NormalizedCharacter],
        length: int,
        validator: Callable[[str], bool],
    ) -> Sequence[NormalizedCharacter] | None:
        for start in range(len(run) - length + 1):
            candidate = run[start : start + length]
            value = "".join(character.value for character in candidate)
            if validator(value):
                return candidate
        return None

    @staticmethod
    def _find_otp(
        run: Sequence[NormalizedCharacter], words: Sequence[AlignedWord]
    ) -> Sequence[NormalizedCharacter] | None:
        for length in range(min(8, len(run)), 3, -1):
            for start in range(len(run) - length + 1):
                candidate = run[start : start + length]
                value = "".join(character.value for character in candidate)
                if validate_otp(value) and _has_otp_cue(
                    words, candidate[0].word_index, candidate[-1].word_index
                ):
                    return candidate
        return None

    def _detect_alphanumeric(
        self,
        segment: Sequence[NormalizedCharacter],
        words: Sequence[AlignedWord],
    ) -> list[DetectionSpan]:
        matches: list[DetectionSpan] = []
        for length, category, validator in (
            (10, "PAN", validate_pan),
            (11, "IFSC", validate_ifsc),
        ):
            for start in range(len(segment) - length + 1):
                candidate = segment[start : start + length]
                value = "".join(character.value for character in candidate)
                if validator(value):
                    matches.append(self._span(category, candidate, words, 0.99))
        return matches

    @staticmethod
    def _span(
        category: str,
        characters: Sequence[NormalizedCharacter],
        words: Sequence[AlignedWord],
        confidence: float,
    ) -> DetectionSpan:
        first_word_idx = min(character.word_index for character in characters)
        last_word_idx = max(character.word_index for character in characters)
        return DetectionSpan(
            category=category,
            first_word_idx=first_word_idx,
            last_word_idx=last_word_idx,
            start=words[first_word_idx].start,
            end=words[last_word_idx].end,
            confidence=confidence,
            validator_result=True,
        )


def _clean_token(token: str) -> str:
    """Case-fold a source token and strip surrounding punctuation."""
    cleaned = unicodedata.normalize("NFC", token).casefold()
    return cleaned.strip(".,;:!?()[]{}\"'")


def _contains_correction(tokens: Sequence[str]) -> bool:
    return any(
        tuple(tokens[index : index + len(phrase)]) == phrase
        for phrase in _CORRECTION_PHRASES
        for index in range(len(tokens) - len(phrase) + 1)
    )


def _may_join(tokens: Sequence[str]) -> bool:
    if not tokens:
        return True
    if all(token in _JOIN_WORDS for token in tokens):
        return True
    return (
        len(tokens) == 2
        and tokens[0] == "for"
        and bool(tokens[1])
        and tokens[1] not in _JOIN_WORDS
    )


def _has_otp_cue(
    words: Sequence[AlignedWord], first_word_idx: int, last_word_idx: int
) -> bool:
    start = max(0, first_word_idx - 8)
    end = min(len(words), last_word_idx + 4)
    context = [_clean_token(word.word).replace("-", "") for word in words[start:end]]
    for index, token in enumerate(context):
        if token in _OTP_CUES:
            return True
        if (
            token in {"onetime"}
            and index + 1 < len(context)
            and context[index + 1] in {"password", "code"}
        ):
            return True
    return False
