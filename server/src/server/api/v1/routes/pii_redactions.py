import logging
import shutil
import tempfile
from pathlib import Path
from typing import Annotated
from zipfile import ZIP_STORED, ZipFile

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from server.config import get_settings
from server.domain.schemas import AlignedWord
from server.observability import log_exception
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

router = APIRouter()
logger = logging.getLogger(__name__)
TRANSCRIPTION_LANGUAGE_CODE = "indic-auto"


@router.post("", response_class=FileResponse)
async def redact_spoken_pii(
    file: Annotated[UploadFile, File()],
) -> FileResponse:
    """Return redacted audio, a tagged transcript, and a metadata-only audit log."""
    settings = get_settings()
    if not file.content_type or not file.content_type.lower().startswith("audio/"):
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only audio files are accepted.",
        )

    max_upload_bytes = settings.max_upload_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_upload_bytes:
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Audio exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )

    working_directory = Path(tempfile.mkdtemp(prefix="bleeper-pii-redaction-"))
    audio_path = working_directory / "original-audio"
    normalized_audio_path = working_directory / "normalized.wav"
    redacted_audio_path = working_directory / "redacted_audio.wav"
    transcript_path = working_directory / "redacted_transcript.txt"
    audit_path = working_directory / "audit.json"
    archive_path = working_directory / "pii-redaction.zip"
    total_bytes = 0
    try:
        with audio_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Audio exceeds the {settings.max_upload_size_mb} MB upload limit.",
                    )
                destination.write(chunk)

        duration = await run_in_threadpool(
            MediaProbeService().duration_seconds, audio_path
        )
        if duration > settings.max_audio_duration_seconds:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Audio exceeds the {settings.max_audio_duration_seconds // 60} minute duration limit.",
            )

        await run_in_threadpool(
            FfmpegAudioExtractor().extract, audio_path, normalized_audio_path
        )
        speech_to_text = create_speech_to_text_provider(
            settings,
            language_code=TRANSCRIPTION_LANGUAGE_CODE,
            use_domain_vocabulary=False,
            log_transcript=False,
        )
        aligner = create_word_aligner(
            settings, language_code=TRANSCRIPTION_LANGUAGE_CODE
        )
        transcript = await run_in_threadpool(
            speech_to_text.transcribe, normalized_audio_path
        )
        timings = await run_in_threadpool(
            aligner.align, normalized_audio_path, transcript
        )
        words = [
            AlignedWord(
                word=timing.word,
                start=timing.start_seconds,
                end=timing.end_seconds,
            )
            for timing in timings
        ]
        spans = await run_in_threadpool(PiiDetector().detect, words)

        await run_in_threadpool(
            FfmpegBleepRenderer().render_audio,
            normalized_audio_path,
            spans,
            redacted_audio_path,
            duration_seconds=duration,
        )
        if not redacted_audio_path.is_file():
            raise LocalProcessingError("Audio redaction did not create an output file.")

        verification_transcript = await run_in_threadpool(
            speech_to_text.transcribe, redacted_audio_path
        )
        verification_timings = await run_in_threadpool(
            aligner.align, redacted_audio_path, verification_transcript
        )
        verification_words = [
            AlignedWord(
                word=timing.word,
                start=timing.start_seconds,
                end=timing.end_seconds,
            )
            for timing in verification_timings
        ]
        leaked_spans = await run_in_threadpool(PiiDetector().detect, verification_words)
        verification = verify_redaction(
            spans,
            leaked_spans,
            duration_seconds=duration,
        )
        logger.info(
            "PII redaction verification leaked_items=%s pii_recall=%.3f "
            "seconds_over_redacted=%.3f",
            verification.leaked_items,
            verification.pii_recall,
            verification.seconds_over_redacted,
        )

        transcript_path.write_text(redact_transcript(words, spans), encoding="utf-8")
        audit_path.write_text(
            create_audit_log(
                spans,
                await run_in_threadpool(sha256_file, audio_path),
                {
                    "leaked_items": verification.leaked_items,
                    "pii_recall": verification.pii_recall,
                    "seconds_over_redacted": verification.seconds_over_redacted,
                },
            ),
            encoding="utf-8",
        )
        with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
            archive.write(redacted_audio_path, "redacted_audio.wav")
            archive.write(transcript_path, "redacted_transcript.txt")
            archive.write(audit_path, "audit.json")

        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="pii-redaction.zip",
            background=BackgroundTask(
                shutil.rmtree, working_directory, ignore_errors=True
            ),
        )
    except HTTPException:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise
    except MediaProbeError as error:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except LocalProcessingError as error:
        log_exception(logger, "spoken PII redaction processing failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Audio transcription or redaction failed.",
        ) from error
    except LocalAlignmentError as error:
        log_exception(logger, "spoken PII word alignment failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Audio word alignment failed.",
        ) from error
    except OSError as error:
        log_exception(
            logger,
            "spoken PII redaction staging failed size_bytes=%s",
            total_bytes,
        )
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not stage or write redaction output.",
        ) from error
    except Exception as error:
        log_exception(logger, "spoken PII redaction failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The audio could not be redacted.",
        ) from error
    finally:
        await file.close()
