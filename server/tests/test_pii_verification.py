from server.domain.schemas import DetectionSpan
from server.services.processing.pii_verification import verify_redaction


def _span(category: str, start: float, end: float) -> DetectionSpan:
    return DetectionSpan(
        category=category,
        first_word_idx=0,
        last_word_idx=0,
        start=start,
        end=end,
        confidence=0.9,
        validator_result=True,
    )


def test_verification_reports_leaks_recall_and_over_redaction_without_values() -> None:
    original = [_span("CARD", 1.0, 1.5), _span("AADHAAR", 2.0, 2.4)]
    leaked = [_span("CARD", 1.02, 1.48)]

    report = verify_redaction(
        original,
        leaked,
        duration_seconds=4.0,
    )

    assert report.leaked_items == (
        {
            "category": "CARD",
            "start": 1.02,
            "end": 1.48,
            "confidence": 0.9,
        },
    )
    assert report.pii_recall == 0.5
    assert report.seconds_over_redacted == 0.32
    assert all("value" not in item for item in report.leaked_items)


def test_verification_has_full_recall_when_no_pii_was_detected() -> None:
    report = verify_redaction([], [], duration_seconds=2.0)

    assert report.leaked_items == ()
    assert report.pii_recall == 1.0
    assert report.seconds_over_redacted == 0.0
