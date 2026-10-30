import re
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath
from uuid import uuid4

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

from server.config import Settings
from server.domain.schemas import DownloadGrant, UploadGrant, UploadRequest


class StorageNotConfiguredError(RuntimeError):
    pass


class UploadTooLargeError(RuntimeError):
    pass


class BlobStorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_upload_grant(self, request: UploadRequest) -> UploadGrant:
        if not self.settings.blob_storage_configured:
            raise StorageNotConfiguredError("Azure Blob Storage credentials are not configured.")

        account_name = self.settings.azure_storage_account_name
        account_key = self.settings.azure_storage_account_key.get_secret_value()
        blob_service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=account_key,
        )
        container = blob_service.get_container_client(self.settings.azure_storage_container)
        try:
            container.create_container()
        except ResourceExistsError:
            pass

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePath(request.file_name).name).strip(".-")
        blob_name = f"uploads/{uuid4().hex}-{safe_name[:100] or 'video'}"
        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.azure_sas_expiry_minutes)
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.settings.azure_storage_container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(create=True, write=True),
            expiry=expires_at,
        )
        upload_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self.settings.azure_storage_container}/{blob_name}?{sas_token}"
        )
        return UploadGrant(blob_name=blob_name, upload_url=upload_url, expires_at=expires_at)

    def create_download_grant(self, blob_name: str) -> DownloadGrant | None:
        if not self.settings.blob_storage_configured:
            raise StorageNotConfiguredError("Azure Blob Storage credentials are not configured.")

        account_name = self.settings.azure_storage_account_name
        account_key = self.settings.azure_storage_account_key.get_secret_value()
        blob_service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=account_key,
        )
        blob = blob_service.get_blob_client(self.settings.azure_storage_container, blob_name)
        if not blob.exists():
            return None

        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.azure_sas_expiry_minutes)
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self.settings.azure_storage_container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expires_at,
        )
        download_url = (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self.settings.azure_storage_container}/{blob_name}?{sas_token}"
        )
        return DownloadGrant(download_url=download_url, expires_at=expires_at)

    def validate_upload_size(self, blob_name: str) -> None:
        blob = self._blob_client(blob_name)
        properties = blob.get_blob_properties()
        max_size_bytes = self.settings.max_upload_size_mb * 1024 * 1024
        if properties.size > max_size_bytes:
            blob.delete_blob()
            raise UploadTooLargeError(
                f"Uploaded video exceeds the {self.settings.max_upload_size_mb} MB limit and was deleted."
            )

    def download_to_path(self, blob_name: str, destination: Path) -> None:
        downloader = self._blob_client(blob_name).download_blob()
        with destination.open("wb") as output_file:
            downloader.readinto(output_file)

    def delete_blob(self, blob_name: str) -> None:
        self._blob_client(blob_name).delete_blob()

    def _blob_client(self, blob_name: str):
        if not self.settings.blob_storage_configured:
            raise StorageNotConfiguredError("Azure Blob Storage credentials are not configured.")

        account_name = self.settings.azure_storage_account_name
        account_key = self.settings.azure_storage_account_key.get_secret_value()
        blob_service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=account_key,
        )
        return blob_service.get_blob_client(self.settings.azure_storage_container, blob_name)