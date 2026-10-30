import logging

from fastapi import APIRouter, HTTPException, status
from server.config import get_settings
from server.domain.schemas import DownloadGrant, DownloadRequest
from server.observability import log_exception
from server.services.blob_storage import BlobStorageService, StorageNotConfiguredError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=DownloadGrant)
def create_download(request: DownloadRequest) -> DownloadGrant:
    settings = get_settings()
    logger.debug("download grant requested")
    if not settings.prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Azure downloads are disabled in local mode.")

    try:
        grant = BlobStorageService(settings).create_download_grant(request.blob_name)
    except StorageNotConfiguredError as error:
        log_exception(logger, "download grant failed because storage is not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processed video was not found.")
    logger.debug("download grant created")
    return grant