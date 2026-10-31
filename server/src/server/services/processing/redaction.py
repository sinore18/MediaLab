from collections.abc import Iterable


def prepare_redaction_intervals(
    intervals: Iterable[tuple[float, float]],
    *,
    duration_seconds: float,
    margin_seconds: float = 0.08,
    merge_gap_seconds: float = 0.15,
) -> tuple[tuple[float, float], ...]:
    """Pad, clip, and merge redaction intervals without retaining source values."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive.")
    if margin_seconds < 0:
        raise ValueError("margin_seconds must not be negative.")
    if merge_gap_seconds < 0:
        raise ValueError("merge_gap_seconds must not be negative.")

    padded: list[tuple[float, float]] = []
    for start, end in intervals:
        if start < 0 or end <= start:
            raise ValueError("Redaction intervals must have valid positive ranges.")
        clipped_start = max(0.0, start - margin_seconds)
        clipped_end = min(duration_seconds, end + margin_seconds)
        if clipped_end > clipped_start:
            padded.append((clipped_start, clipped_end))

    merged: list[tuple[float, float]] = []
    for start, end in sorted(padded):
        if merged and start - merged[-1][1] < merge_gap_seconds:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)
