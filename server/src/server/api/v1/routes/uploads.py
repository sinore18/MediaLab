import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from server.config import get_settings
from server.observability import log_exception
from server.services.media.probe import MediaProbeError, MediaProbeService
from server.services.processing.local_aligner import LocalAlignmentError
from server.services.processing.local_processing import (
    LocalProcessingError,
    create_local_video_processor,
)
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_class=FileResponse)
async def upload_video(file: Annotated[UploadFile, File()]) -> FileResponse:
    settings = get_settings()
    logger.debug("video upload started content_type=%s", file.content_type)
    if not file.content_type or not file.content_type.lower().startswith("video/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only video files are accepted.")
    if file.size is not None and file.size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Video exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )

    working_directory = Path(tempfile.mkdtemp(prefix="bleeper-upload-"))
    video_path = working_directory / "video"
    output_path = working_directory / "processed.mp4"
    total_bytes = 0
    try:
        with video_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Video exceeds the {settings.max_upload_size_mb} MB upload limit.",
                    )
                destination.write(chunk)

        logger.debug("video upload staged size_bytes=%s", total_bytes)
        duration = MediaProbeService().duration_seconds(video_path)
        logger.debug("video upload validated duration_seconds=%s", duration)
        if duration > settings.max_video_duration_seconds:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Video exceeds the {settings.max_video_duration_seconds // 60} minute duration limit.",
            )
        logger.debug("video processing started")
        processor = create_local_video_processor(settings)
        processed_video = await run_in_threadpool(
            processor.process, video_path, output_path
        )
        logger.debug("video processing completed")
    except HTTPException:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise
    except MediaProbeError as error:
        logger.debug("video upload media probe failed reason=%s", error)
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except (LocalAlignmentError, LocalProcessingError) as error:
        log_exception(logger, "video processing failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The video could not be processed.",
        ) from error
    except OSError as error:
        log_exception(logger, "video upload staging failed size_bytes=%s", total_bytes)
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not stage the video.") from error
    except Exception as error:
        log_exception(logger, "video processing failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The video could not be processed.",
        ) from error
    finally:
        await file.close()

    return FileResponse(
        processed_video.path,
        media_type="video/mp4",
        filename="bleeper-processed.mp4",
        headers={
            "X-Video-Duration-Seconds": str(duration),
            "X-Bleep-Timestamps": json.dumps(
                processed_video.bleep_timestamps, separators=(",", ":")
            ),
            "X-Bleep-Spans": json.dumps(
                processed_video.bleep_spans, separators=(",", ":")
            ),
        },
        background=BackgroundTask(shutil.rmtree, working_directory, ignore_errors=True),
    )
