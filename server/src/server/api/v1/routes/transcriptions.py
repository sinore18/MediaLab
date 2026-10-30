import logging
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from server.config import get_settings
from server.domain.schemas import TranscriptionResponse
from server.observability import log_exception
from server.services.media.probe import MediaProbeError, MediaProbeService
from server.services.processing.local_aligner import LocalAlignmentError
from server.services.processing.local_processing import (
    FfmpegAudioExtractor,
    LocalProcessingError,
    create_speech_to_text_provider,
    create_word_aligner,
)

router = APIRouter()
logger = logging.getLogger(__name__)
TRANSCRIPTION_LANGUAGE_CODE = "indic-auto"


@router.post("", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: Annotated[UploadFile, File()],
) -> TranscriptionResponse:
    settings = get_settings()
    if not file.content_type or not file.content_type.lower().startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only audio files are accepted.",
        )

    max_upload_bytes = settings.max_upload_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Audio exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )

    provider_name = settings.stt_provider.strip().casefold()
    if provider_name not in {"vachana", "gnani"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio transcription requires the Gnani STT provider. Set STT_PROVIDER=gnani and configure STT_API_KEY.",
        )

    working_directory = Path(tempfile.mkdtemp(prefix="bleeper-transcription-"))
    audio_path = working_directory / "audio"
    normalized_audio_path = working_directory / "normalized.wav"
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

        duration = MediaProbeService().duration_seconds(audio_path)
        if duration > settings.max_audio_duration_seconds:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Audio exceeds the {settings.max_audio_duration_seconds // 60} minute duration limit.",
            )

        logger.info(
            "audio transcription started duration_seconds=%.2f language_code=%s",
            duration,
            TRANSCRIPTION_LANGUAGE_CODE,
        )
        await run_in_threadpool(
            FfmpegAudioExtractor().extract, audio_path, normalized_audio_path
        )
        speech_to_text = create_speech_to_text_provider(
            settings,
            language_code=TRANSCRIPTION_LANGUAGE_CODE,
            use_domain_vocabulary=False,
        )
        aligner = create_word_aligner(
            settings, language_code=TRANSCRIPTION_LANGUAGE_CODE
        )
        transcript = await run_in_threadpool(
            speech_to_text.transcribe, normalized_audio_path
        )
        words = await run_in_threadpool(
            aligner.align, normalized_audio_path, transcript
        )
        logger.info("audio transcription completed word_count=%d", len(words))
        return TranscriptionResponse(
            transcript=transcript,
            duration_seconds=duration,
            words=list(words),
        )
    except HTTPException:
        raise
    except MediaProbeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except LocalProcessingError as error:
        log_exception(logger, "audio transcription failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)
        ) from error
    except LocalAlignmentError as error:
        log_exception(logger, "audio word alignment failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    except OSError as error:
        log_exception(
            logger, "audio transcription staging failed size_bytes=%s", total_bytes
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not stage the audio file.",
        ) from error
    except Exception as error:
        log_exception(logger, "audio transcription failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The audio could not be transcribed.",
        ) from error
    finally:
        await file.close()
        shutil.rmtree(working_directory, ignore_errors=True)
