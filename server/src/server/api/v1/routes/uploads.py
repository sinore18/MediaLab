import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from azure.core.exceptions import AzureError
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from server.config import get_settings
from server.domain.schemas import (
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadGrant,
    UploadRequest,
)
from server.observability import log_exception
from server.services.blob_storage import (
    BlobStorageService,
    StorageNotConfiguredError,
    UploadTooLargeError,
)
from server.services.media.probe import MediaProbeError, MediaProbeService
from server.services.processing.local_aligner import LocalAlignmentError
from server.services.processing.local_processing import (
    LocalProcessingError,
    create_local_video_processor,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/local", response_class=FileResponse)
async def upload_local_video(file: Annotated[UploadFile, File()]) -> FileResponse:
    settings = get_settings()
    logger.debug("local upload started content_type=%s", file.content_type)
    if settings.prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local uploads are disabled in production.")
    if not file.content_type or not file.content_type.lower().startswith("video/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only video files are accepted.")
    if file.size is not None and file.size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Video exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )

    working_directory = Path(tempfile.mkdtemp(prefix="bleeper-local-"))
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

        logger.debug("local upload staged size_bytes=%s", total_bytes)
        duration = MediaProbeService().duration_seconds(video_path)
        logger.debug("local upload validated duration_seconds=%s", duration)
        if duration > settings.max_video_duration_seconds:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Video exceeds the {settings.max_video_duration_seconds // 60} minute duration limit.",
            )
        logger.debug("local processing started")
        processor = create_local_video_processor(settings)
        processed_video = await run_in_threadpool(
            processor.process, video_path, output_path
        )
        logger.debug("local processing completed")
    except HTTPException:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise
    except MediaProbeError as error:
        logger.debug("local upload media probe failed reason=%s", error)
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except (LocalAlignmentError, LocalProcessingError) as error:
        log_exception(logger, "local video processing failed")
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The video could not be processed.",
        ) from error
    except OSError as error:
        log_exception(logger, "local upload staging failed size_bytes=%s", total_bytes)
        shutil.rmtree(working_directory, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not stage the local video.") from error
    except Exception as error:
        log_exception(logger, "local video processing failed")
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


@router.post("", response_model=UploadGrant, status_code=status.HTTP_201_CREATED)
def create_upload(request: UploadRequest) -> UploadGrant:
    settings = get_settings()
    logger.debug("upload grant requested size_bytes=%s duration_seconds=%s", request.file_size_bytes, request.duration_seconds)
    if not settings.prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Azure uploads are disabled in local mode.")

    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    if request.file_size_bytes > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Video exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )
    if request.duration_seconds > settings.max_video_duration_seconds:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Video exceeds the {settings.max_video_duration_seconds // 60} minute duration limit.",
        )

    try:
        grant = BlobStorageService(settings).create_upload_grant(request)
        logger.debug("upload grant created")
        return grant
    except StorageNotConfiguredError as error:
        log_exception(logger, "upload grant failed because storage is not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except AzureError as error:
        log_exception(logger, "Azure failed to create an upload grant")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure Blob Storage could not create an upload URL.",
        ) from error


@router.post("/complete", response_model=UploadCompleteResponse)
def complete_upload(request: UploadCompleteRequest) -> UploadCompleteResponse:
    settings = get_settings()
    logger.debug("upload completion started")
    if not settings.prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Azure uploads are disabled in local mode.")

    storage = BlobStorageService(settings)
    try:
        storage.validate_upload_size(request.blob_name)
        logger.debug("uploaded blob size validated")
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "uploaded-video"
            storage.download_to_path(request.blob_name, video_path)
            logger.debug("uploaded blob downloaded for validation")
            duration = MediaProbeService().duration_seconds(video_path)
            logger.debug("uploaded blob media validated duration_seconds=%s", duration)
    except UploadTooLargeError as error:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
    except MediaProbeError as error:
        storage.delete_blob(request.blob_name)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except StorageNotConfiguredError as error:
        log_exception(logger, "upload completion failed because storage is not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except AzureError as error:
        log_exception(logger, "Azure failed to verify the uploaded blob")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The uploaded Blob could not be verified.",
        ) from error

    if duration > settings.max_video_duration_seconds:
        storage.delete_blob(request.blob_name)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Video exceeds the {settings.max_video_duration_seconds // 60} minute duration limit and was deleted.",
        )
    logger.debug("upload completion succeeded")
    return UploadCompleteResponse(blob_name=request.blob_name, duration_seconds=duration)