from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from server.domain.schemas import DetectionSpan
from server.services.processing.redaction import prepare_redaction_intervals


@dataclass(frozen=True)
class RedactionVerification:
    """Privacy-safe verification results for redacted audio."""

    leaked_items: tuple[dict[str, float | str | None], ...]
    pii_recall: float
    seconds_over_redacted: float


def verify_redaction(
    original_spans: Sequence[DetectionSpan],
    leaked_spans: Sequence[DetectionSpan],
    *,
    duration_seconds: float,
    margin_seconds: float = 0.08,
    merge_gap_seconds: float = 0.15,
) -> RedactionVerification:
    """Compare re-detected spans and estimate redacted time beyond PII spans."""
    redaction_intervals = prepare_redaction_intervals(
        ((span.start, span.end) for span in original_spans),
        duration_seconds=duration_seconds,
        margin_seconds=margin_seconds,
        merge_gap_seconds=merge_gap_seconds,
    )
    matched_original: set[int] = set()
    for leaked in leaked_spans:
        for index, original in enumerate(original_spans):
            if index in matched_original or leaked.category != original.category:
                continue
            padded_start = max(0.0, original.start - margin_seconds)
            padded_end = min(duration_seconds, original.end + margin_seconds)
            if leaked.start < padded_end and leaked.end > padded_start:
                matched_original.add(index)
                break

    redacted_pii_duration = _union_duration(
        (max(start, span.start), min(end, span.end))
        for start, end in redaction_intervals
        for span in original_spans
        if max(start, span.start) < min(end, span.end)
    )
    redacted_duration = _union_duration(redaction_intervals)
    seconds_over_redacted = round(
        max(0.0, redacted_duration - redacted_pii_duration), 3
    )

    recall = (
        (len(original_spans) - len(matched_original)) / len(original_spans)
        if original_spans
        else 1.0
    )
    return RedactionVerification(
        leaked_items=tuple(
            {
                "category": span.category,
                "start": round(span.start, 3),
                "end": round(span.end, 3),
                "confidence": span.confidence,
            }
            for span in leaked_spans
        ),
        pii_recall=recall,
        seconds_over_redacted=seconds_over_redacted,
    )


def _union_duration(intervals: Iterable[tuple[float, float]]) -> float:
    """Measure the duration covered by overlapping intervals once."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)
