import json
import logging
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from server.config import get_settings
from server.observability import log_exception
from server.services.processing.contracts import (
    BleepRenderer,
    ProfanityDetector,
    SpeechToTextProvider,
    WordAligner,
)
from server.services.processing.local_aligner import LocalMMSWordAligner

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ProcessingPipeline:
    def __init__(
        self,
        speech_to_text: SpeechToTextProvider,
        profanity_detector: ProfanityDetector,
        renderer: BleepRenderer,
        word_aligner: WordAligner | None = None,
    ) -> None:
        self.speech_to_text = speech_to_text
        settings = get_settings()
        self.word_aligner = word_aligner or LocalMMSWordAligner(
            device=settings.local_alignment_device,
            language=settings.stt_language_code,
        )
        self.profanity_detector = profanity_detector
        self.renderer = renderer

    def process(
        self, video_path: Path, audio_path: Path, output_path: Path
    ) -> tuple[Path, tuple[tuple[float, float], ...]]:
        logger.info("processing started")
        transcript = self._run_step(
            "transcription", self.speech_to_text.transcribe, audio_path
        )
        logger.info("transcription completed characters=%d", len(transcript))
        words = self._run_step(
            "word_alignment", self.word_aligner.align, audio_path, transcript
        )
        logger.info("word alignment completed word_count=%d", len(words))
        matches = self._run_step(
            "profanity_detection", self.profanity_detector.find_matches, words
        )
        logger.info(
            "profanity detection completed word_count=%d match_count=%d",
            len(words),
            len(matches),
        )
        for match in matches:
            logger.info(
                "profanity identified kind=%s text=%s start_seconds=%.3f end_seconds=%.3f",
                match.kind,
                json.dumps(match.word, ensure_ascii=False),
                match.start_seconds,
                match.end_seconds,
            )
        # for word in words:
        #     logger.info(
        #         "%s: %.3f-%.3f",
        #         json.dumps(word.word, ensure_ascii=False),
        #         word.start_seconds,
        #         word.end_seconds,
        #     )
        result_path = self._run_step(
            "rendering", self.renderer.render, video_path, matches, output_path
        )
        logger.info("processing completed")
        bleep_spans = tuple(
            sorted(
                (
                    match.start_seconds,
                    match.end_seconds,
                )
                for match in matches
                if match.end_seconds > match.start_seconds
            )
        )
        return result_path, bleep_spans

    @staticmethod
    def _run_step(name: str, operation: Callable[..., T], *args: object) -> T:
        started_at = perf_counter()
        logger.info("processing step started step=%s", name)
        try:
            result = operation(*args)
        except Exception:
            log_exception(logger, "processing step failed step=%s", name)
            raise
        logger.info(
            "processing step completed step=%s duration_ms=%.2f",
            name,
            (perf_counter() - started_at) * 1000,
        )
        return result
