import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from server.config import get_settings
from server.domain.schemas import AlignedWord
from server.services.media.probe import MediaProbeError, MediaProbeService
from server.services.processing.local_aligner import LocalAlignmentError
from server.services.processing.local_processing import (
    FfmpegAudioExtractor,
    FfmpegBleepRenderer,
    LocalProcessingError,
    create_speech_to_text_provider,
    create_word_aligner,
)
from server.services.processing.pii_detector import PiiDetector
from server.services.processing.pii_outputs import (
    create_audit_log,
    redact_transcript,
    sha256_file,
)
from server.services.processing.pii_verification import verify_redaction


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for audio PII redaction."""
    parser = argparse.ArgumentParser(
        prog="pii-redact",
        description="Redact spoken PII from an audio recording.",
    )
    parser.add_argument("input_audio", type=Path, help="Audio file to redact.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("pii-redaction-output"),
        help="Directory for redacted audio, transcript, and audit (default: %(default)s).",
    )
    parser.add_argument(
        "--mode",
        choices=("beep", "silence"),
        default="beep",
        help="Replace detected spans with a tone or silence.",
    )
    parser.add_argument(
        "--margin-ms",
        type=float,
        default=80.0,
        help="Padding on each side of detected spans in milliseconds (default: 80).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run transcription, detection, redaction, and reverification."""
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.margin_ms < 0:
        parser.error("--margin-ms must not be negative.")
    if not arguments.input_audio.is_file():
        parser.error(f"Input audio does not exist: {arguments.input_audio}")

    settings = get_settings()
    output_directory: Path = arguments.output_dir
    redacted_path = output_directory / "redacted_audio.wav"
    transcript_path = output_directory / "redacted_transcript.txt"
    audit_path = output_directory / "audit.json"
    if output_directory.resolve() == arguments.input_audio.resolve().parent:
        parser.error("Choose an output directory separate from the input audio folder.")

    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        duration = MediaProbeService().duration_seconds(arguments.input_audio)
        if duration > settings.max_audio_duration_seconds:
            parser.error(
                f"Audio exceeds the configured {settings.max_audio_duration_seconds} second limit."
            )

        with tempfile.TemporaryDirectory(prefix="bleeper-pii-cli-") as temporary:
            normalized_path = Path(temporary) / "normalized.wav"
            FfmpegAudioExtractor().extract(arguments.input_audio, normalized_path)
            speech_to_text = create_speech_to_text_provider(
                settings,
                use_domain_vocabulary=False,
                log_transcript=False,
            )
            aligner = create_word_aligner(settings)
            transcript = speech_to_text.transcribe(normalized_path)
            timings = aligner.align(normalized_path, transcript)
            words = [
                AlignedWord(
                    word=timing.word,
                    start=timing.start_seconds,
                    end=timing.end_seconds,
                )
                for timing in timings
            ]
            detector = PiiDetector()
            spans = detector.detect(words)
            margin_seconds = arguments.margin_ms / 1000
            FfmpegBleepRenderer().render_audio(
                normalized_path,
                spans,
                redacted_path,
                duration_seconds=duration,
                mode=arguments.mode,
                margin_seconds=margin_seconds,
            )
            if not redacted_path.is_file():
                raise LocalProcessingError(
                    "Audio redaction did not create an output file."
                )

            verification_transcript = speech_to_text.transcribe(redacted_path)
            verification_timings = aligner.align(redacted_path, verification_transcript)
            verification_words = [
                AlignedWord(
                    word=timing.word,
                    start=timing.start_seconds,
                    end=timing.end_seconds,
                )
                for timing in verification_timings
            ]
            leaked_spans = detector.detect(verification_words)
            verification = verify_redaction(
                spans,
                leaked_spans,
                duration_seconds=duration,
                margin_seconds=margin_seconds,
            )

            transcript_path.write_text(
                redact_transcript(words, spans), encoding="utf-8"
            )
            audit_path.write_text(
                create_audit_log(
                    spans,
                    sha256_file(arguments.input_audio),
                    {
                        "leaked_items": verification.leaked_items,
                        "pii_recall": verification.pii_recall,
                        "seconds_over_redacted": verification.seconds_over_redacted,
                    },
                ),
                encoding="utf-8",
            )
    except (
        MediaProbeError,
        LocalProcessingError,
        LocalAlignmentError,
        OSError,
    ) as error:
        print(
            f"pii-redact: {type(error).__name__}; audio redaction did not complete.",
            file=sys.stderr,
        )
        return 1

    print(f"Redacted audio: {redacted_path}")
    print(f"Redacted transcript: {transcript_path}")
    print(f"Audit log: {audit_path}")
    print(f"PII recall: {verification.pii_recall:.3f}")
    print(f"Seconds over-redacted: {verification.seconds_over_redacted:.3f}")
    print(f"Leaked detections: {len(verification.leaked_items)}")
    return 0
