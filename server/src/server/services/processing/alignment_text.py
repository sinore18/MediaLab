"""Text helpers for forced alignment: spoken expansion of digits/acronyms and timing gap filling.

Pure Python (no torch / server imports) so it is cheap and easy to unit test.
"""
from __future__ import annotations

import re
import unicodedata

# Spoken digit words per base language code (native script; the aligner romanizes them).
DIGIT_WORDS: dict[str, tuple[str, ...]] = {
    "en": tuple("zero one two three four five six seven eight nine".split()),
    "hi": tuple("शून्य एक दो तीन चार पाँच छह सात आठ नौ".split()),
    "bn": tuple("শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয়".split()),
    "gu": tuple("શૂન્ય એક બે ત્રણ ચાર પાંચ છ સાત આઠ નવ".split()),
    "kn": tuple("ಸೊನ್ನೆ ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು ಐದು ಆರು ಏಳು ಎಂಟು ಒಂಬತ್ತು".split()),
    "ml": tuple("പൂജ്യം ഒന്ന് രണ്ട് മൂന്ന് നാല് അഞ്ച് ആറ് ഏഴ് എട്ട് ഒമ്പത്".split()),
    "mr": tuple("शून्य एक दोन तीन चार पाच सहा सात आठ नऊ".split()),
    "pa": tuple("ਸਿਫਰ ਇੱਕ ਦੋ ਤਿੰਨ ਚਾਰ ਪੰਜ ਛੇ ਸੱਤ ਅੱਠ ਨੌਂ".split()),
    "ta": tuple("பூஜ்ஜியம் ஒன்று இரண்டு மூன்று நான்கு ஐந்து ஆறு ஏழு எட்டு ஒன்பது".split()),
    "te": tuple("సున్నా ఒకటి రెండు మూడు నాలుగు ఐదు ఆరు ఏడు ఎనిమిది తొమ్మిది".split()),
}

# English letter names, used to spell PAN/IFSC-style tokens such as GCPPA7536G.
LETTER_NAMES: dict[str, str] = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ay bee see dee ee eff gee aitch eye jay kay el em en oh pee cue are ess tee you vee doubleyou ex why zed".split(),
    )
)

_ACRONYM = re.compile(r"[A-Z]{2,12}")


def base_language(language: str) -> str:
    return language.strip().lower().replace("_", "-").split("-", 1)[0]


def spoken_pieces(word: str, language: str = "en") -> list[str]:
    """Split one transcript word into pieces that can be spoken and aligned.

    Words with digits become one spoken word per digit (letters inside the token are spelled
    with English letter names). All-caps acronyms (OTP, PAN, IFSC) are spelled out. Anything
    else is returned unchanged.
    """
    has_digit = any(unicodedata.decimal(c, None) is not None for c in word)
    if not has_digit:
        if _ACRONYM.fullmatch(word):
            return [LETTER_NAMES[c] for c in word]
        return [word]

    table = DIGIT_WORDS.get(base_language(language), DIGIT_WORDS["en"])
    pieces: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            pieces.append("".join(buffer))
            buffer.clear()

    for c in word:
        digit = unicodedata.decimal(c, None)  # handles Devanagari, Bengali, ... digits too
        if digit is not None:
            flush()
            pieces.append(table[digit])
        elif c.isascii() and c.isalpha():
            flush()
            pieces.append(LETTER_NAMES[c.upper()])
        elif unicodedata.category(c)[0] in {"L", "M"}:  # non-ASCII letters / combining marks
            buffer.append(c)
        else:  # punctuation, currency symbols, separators
            flush()
    flush()
    return pieces


def fill_unaligned(
    aligned: dict[int, tuple[float, float]],
    unaligned: set[int],
    audio_seconds: float,
    min_width: float = 0.05,
) -> dict[int, tuple[float, float]]:
    """Interpolate timings for words the aligner could not place.

    Consecutive unaligned words share the gap between their nearest aligned neighbours.
    """
    runs: list[list[int]] = []
    for idx in sorted(unaligned):
        if runs and not any(runs[-1][-1] < j < idx for j in aligned):
            runs[-1].append(idx)
        else:
            runs.append([idx])

    result: dict[int, tuple[float, float]] = {}
    for run in runs:
        lo = max((aligned[j][1] for j in aligned if j < run[0]), default=0.0)
        hi = min((aligned[j][0] for j in aligned if j > run[-1]), default=audio_seconds)
        if hi - lo < min_width * len(run):
            hi = lo + min_width * len(run)
        step = (hi - lo) / len(run)
        for k, idx in enumerate(run):
            result[idx] = (lo + k * step, lo + (k + 1) * step)
    return result