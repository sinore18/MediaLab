import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from server.domain.schemas import AlignedWord, DetectionSpan


def redact_transcript(
    words: Sequence[AlignedWord], spans: Sequence[DetectionSpan]
) -> str:
    """Replace detected aligned-word ranges with category tags."""
    tags_by_index: dict[int, list[str]] = {}
    covered_indexes: set[int] = set()
    for span in spans:
        if span.last_word_idx >= len(words) or span.last_word_idx < span.first_word_idx:
            raise ValueError("A detector span is outside the aligned transcript.")
        tags_by_index.setdefault(span.first_word_idx, []).append(f"[{span.category}]")
        covered_indexes.update(range(span.first_word_idx, span.last_word_idx + 1))

    output: list[str] = []
    for index, word in enumerate(words):
        output.extend(tags_by_index.get(index, ()))
        if index not in covered_indexes:
            output.append(word.word)
    return " ".join(output)


def create_audit_log(
    spans: Sequence[DetectionSpan],
    original_sha256: str,
    verification: Mapping[str, object] | None = None,
) -> str:
    """Serialize detection metadata without including detected source values."""
    audit = {
        "original_sha256": original_sha256,
        "detections": [
            {
                "category": span.category,
                "start": span.start,
                "end": span.end,
                "confidence": span.confidence,
                "validator_result": span.validator_result,
            }
            for span in spans
        ],
    }
    if verification is not None:
        audit["verification"] = dict(verification)
    return json.dumps(audit, ensure_ascii=False, indent=2) + "\n"


def sha256_file(path: Path) -> str:
    """Return a file's SHA-256 digest using bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
