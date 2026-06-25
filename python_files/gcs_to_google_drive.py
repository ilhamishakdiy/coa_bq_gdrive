"""Copy exported files from Google Cloud Storage to Google Drive."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import fnmatch
import logging
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote


# =============================================================================
# Third-party imports
# =============================================================================

from dotenv import load_dotenv
from google import auth
from google.api_core.exceptions import GoogleAPIError
from google.cloud import storage
from google.oauth2 import service_account
from googleapiclient import discovery
from googleapiclient.http import MediaIoBaseUpload


# =============================================================================
# Environment and logging configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Constants
# =============================================================================

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
)
MINIMUM_UPLOAD_CHUNK_SIZE = 256 * 1024


# =============================================================================
# Environment helpers
# =============================================================================

def _required_environment_value(name: str) -> str:
    """Return a required, non-empty environment variable."""

    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable {name} is not set.")
    return value


def _optional_environment_value(name: str) -> str | None:
    """Return a trimmed environment variable or None when blank."""

    value = os.getenv(name, "").strip()
    return value or None


def _project_environment_value(name: str) -> str:
    """Return a dedicated project ID or the legacy project ID fallback."""

    project_id = _optional_environment_value(name)
    legacy_project_id = _optional_environment_value("GCP_PROJECT_ID")

    if project_id:
        return project_id
    if legacy_project_id:
        return legacy_project_id

    raise ValueError(
        f"Required environment variable {name} is not set. "
        "GCP_PROJECT_ID may be used as a backward-compatible fallback."
    )


def _environment_boolean(name: str, default: bool) -> bool:
    """Parse a conventional boolean environment variable."""

    value = os.getenv(name)
    if value is None:
        return default

    normalized_value = value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def _stream_chunk_size() -> int:
    """Return a valid chunk size for streaming between GCS and Drive."""

    configured_size_mb = os.getenv("STREAM_CHUNK_SIZE_MB", "8").strip()

    try:
        chunk_size = int(configured_size_mb) * 1024 * 1024
    except ValueError as error:
        raise ValueError("STREAM_CHUNK_SIZE_MB must be a whole number.") from error

    if chunk_size <= 0 or chunk_size % MINIMUM_UPLOAD_CHUNK_SIZE != 0:
        raise ValueError(
            "STREAM_CHUNK_SIZE_MB must produce a positive chunk size that is "
            "a multiple of 256 KiB."
        )

    return chunk_size


# =============================================================================
# Authentication and clients
# =============================================================================

def _load_credentials(credentials_path: str | None) -> Any:
    """Load a service-account key or Application Default Credentials."""

    # -------------------------------------------------------------------------
    # Use the service-account key configured in .env when one is supplied.
    # -------------------------------------------------------------------------

    if credentials_path:
        resolved_path = Path(credentials_path).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = PROJECT_ROOT / resolved_path

        if not resolved_path.is_file():
            raise FileNotFoundError(
                f"Google credentials file was not found: {resolved_path}"
            )

        return service_account.Credentials.from_service_account_file(
            str(resolved_path),
            scopes=GOOGLE_SCOPES,
        )

    # -------------------------------------------------------------------------
    # Use Application Default Credentials in managed Google environments.
    # -------------------------------------------------------------------------

    credentials, _ = auth.default(scopes=GOOGLE_SCOPES)
    return credentials


def _create_clients() -> tuple[storage.Client, Any]:
    """Create authenticated Cloud Storage and Google Drive clients."""

    gcs_project_id = _project_environment_value("GCS_PROJECT_ID")
    credentials_path = _optional_environment_value(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    credentials = _load_credentials(credentials_path)

    storage_client = storage.Client(
        project=gcs_project_id,
        credentials=credentials,
    )
    drive_client = discovery.build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    return storage_client, drive_client


# =============================================================================
# GCS object helpers
# =============================================================================

def _split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """Split a GCS URI into bucket and wildcard object name."""

    uri_match = re.fullmatch(r"gs://([^/]+)/(.+)", gcs_uri)
    if not uri_match:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    return uri_match.group(1), uri_match.group(2)


def _list_matching_blobs(
    storage_client: storage.Client,
    gcs_uri: str,
) -> list[Any]:
    """List only the GCS objects matching the supplied wildcard URI."""

    bucket_name, wildcard_object_name = _split_gcs_uri(gcs_uri)
    object_prefix = wildcard_object_name.split("*", maxsplit=1)[0]
    candidate_blobs = storage_client.list_blobs(
        bucket_name,
        prefix=object_prefix,
    )
    matching_blobs = [
        blob
        for blob in candidate_blobs
        if fnmatch.fnmatchcase(blob.name, wildcard_object_name)
    ]

    if not matching_blobs:
        raise FileNotFoundError(
            f"No GCS objects matched the export URI: {gcs_uri}"
        )

    return sorted(matching_blobs, key=lambda blob: blob.name)


def _build_merged_object_name(wildcard_object_name: str) -> str:
    """Replace the export wildcard with a stable merged-file marker."""

    if "*" not in wildcard_object_name:
        raise ValueError("The GCS export URI must contain a wildcard (*).")

    return wildcard_object_name.replace("*", "merged", 1)


def _merge_csv_shards(
    storage_client: storage.Client,
    gcs_uri: str,
    stream_chunk_size: int,
    delete_source_shards: bool,
) -> Any:
    """Merge CSV shards into one GCS object and retain only one header row."""

    # -------------------------------------------------------------------------
    # Resolve and sort source shards before creating the destination object.
    # -------------------------------------------------------------------------

    bucket_name, wildcard_object_name = _split_gcs_uri(gcs_uri)
    merged_object_name = _build_merged_object_name(wildcard_object_name)
    source_blobs = [
        blob
        for blob in _list_matching_blobs(storage_client, gcs_uri)
        if blob.name != merged_object_name
    ]

    if not source_blobs:
        existing_merged_blob = storage_client.bucket(bucket_name).blob(
            merged_object_name
        )
        if existing_merged_blob.exists():
            LOGGER.info(
                "Using existing merged GCS object: gs://%s/%s",
                bucket_name,
                merged_object_name,
            )
            return existing_merged_blob

        raise FileNotFoundError(
            f"No source CSV shards were found for: {gcs_uri}"
        )

    merged_blob = storage_client.bucket(bucket_name).blob(merged_object_name)
    LOGGER.info(
        "Merging %d CSV shards into gs://%s/%s",
        len(source_blobs),
        bucket_name,
        merged_object_name,
    )

    # -------------------------------------------------------------------------
    # Stream each shard into GCS and skip duplicate headers after shard one.
    # -------------------------------------------------------------------------

    try:
        with merged_blob.open(
            "wb",
            chunk_size=stream_chunk_size,
            content_type="text/csv",
        ) as merged_stream:
            for shard_index, source_blob in enumerate(source_blobs):
                LOGGER.info(
                    "Appending shard %d/%d: gs://%s/%s",
                    shard_index + 1,
                    len(source_blobs),
                    bucket_name,
                    source_blob.name,
                )

                with source_blob.open(
                    "rb",
                    chunk_size=stream_chunk_size,
                ) as source_stream:
                    if shard_index > 0:
                        source_stream.readline()

                    shutil.copyfileobj(
                        source_stream,
                        merged_stream,
                        length=stream_chunk_size,
                    )
    except GoogleAPIError:
        LOGGER.exception(
            "Failed to merge CSV shards for %s",
            gcs_uri,
        )
        raise

    # -------------------------------------------------------------------------
    # Delete source shards only after the merged object is fully committed.
    # -------------------------------------------------------------------------

    if delete_source_shards:
        for source_blob in source_blobs:
            source_blob.delete()
            LOGGER.info(
                "Deleted source shard gs://%s/%s",
                bucket_name,
                source_blob.name,
            )

    LOGGER.info(
        "CSV shard merge completed: gs://%s/%s",
        bucket_name,
        merged_object_name,
    )
    return merged_blob


# =============================================================================
# Public transfer function
# =============================================================================

def transfer_gcs_to_google_drive(
    gcs_uri: str | None = None,
) -> list[dict[str, str]]:
    """Merge optional CSV shards and upload GCS files to Google Drive."""

    # -------------------------------------------------------------------------
    # Use the URI supplied by the flow runner, or fall back to .env.
    # -------------------------------------------------------------------------

    resolved_gcs_uri = gcs_uri or _required_environment_value("GCS_EXPORT_URI")
    configured_bucket = _required_environment_value("GCS_BUCKET_NAME")
    drive_folder_id = _required_environment_value("DRIVE_FOLDER_ID")
    delete_after_upload = _environment_boolean(
        "DELETE_GCS_AFTER_DRIVE_UPLOAD",
        default=False,
    )
    merge_gcs_shards = _environment_boolean(
        "MERGE_GCS_SHARDS",
        default=True,
    )
    delete_source_shards = _environment_boolean(
        "DELETE_GCS_SHARDS_AFTER_MERGE",
        default=True,
    )
    stream_chunk_size = _stream_chunk_size()

    bucket_name, _ = _split_gcs_uri(resolved_gcs_uri)
    if bucket_name != configured_bucket:
        raise ValueError(
            "The GCS URI bucket must match GCS_BUCKET_NAME."
        )

    storage_client, drive_client = _create_clients()

    # -------------------------------------------------------------------------
    # Merge BigQuery CSV shards before uploading when configured.
    # -------------------------------------------------------------------------

    if merge_gcs_shards:
        blobs = [
            _merge_csv_shards(
                storage_client=storage_client,
                gcs_uri=resolved_gcs_uri,
                stream_chunk_size=stream_chunk_size,
                delete_source_shards=delete_source_shards,
            )
        ]
    else:
        blobs = _list_matching_blobs(storage_client, resolved_gcs_uri)

    # -------------------------------------------------------------------------
    # Stream each object directly from GCS into a resumable Drive upload.
    # -------------------------------------------------------------------------

    uploaded_files: list[dict[str, str]] = []
    for blob in blobs:
        file_name = Path(blob.name).name
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        try:
            LOGGER.info(
                "Streaming gs://%s/%s directly to Google Drive",
                bucket_name,
                blob.name,
            )

            with blob.open(
                "rb",
                chunk_size=stream_chunk_size,
            ) as gcs_stream:
                media = MediaIoBaseUpload(
                    gcs_stream,
                    mimetype=mime_type,
                    chunksize=stream_chunk_size,
                    resumable=True,
                )
                drive_file = (
                    drive_client.files()
                    .create(
                        body={
                            "name": file_name,
                            "parents": [drive_folder_id],
                        },
                        media_body=media,
                        fields="id,name,webViewLink",
                        supportsAllDrives=True,
                    )
                    .execute()
                )

            # -----------------------------------------------------------------
            # Return a usable Drive URL for each uploaded file.
            # -----------------------------------------------------------------

            drive_file_id = drive_file["id"]
            drive_url = drive_file.get(
                "webViewLink",
                f"https://drive.google.com/file/d/"
                f"{quote(drive_file_id)}/view",
            )
            uploaded_files.append(
                {
                    "gcs_uri": f"gs://{bucket_name}/{blob.name}",
                    "drive_file_id": drive_file_id,
                    "drive_url": drive_url,
                }
            )
            LOGGER.info(
                "Uploaded %s to Google Drive. File ID: %s",
                file_name,
                drive_file_id,
            )

            # -----------------------------------------------------------------
            # Delete from GCS only after a successful Drive upload.
            # -----------------------------------------------------------------

            if delete_after_upload:
                blob.delete()
                LOGGER.info("Deleted gs://%s/%s", bucket_name, blob.name)

        except GoogleAPIError:
            LOGGER.exception(
                "Failed to transfer gs://%s/%s to Google Drive",
                bucket_name,
                blob.name,
            )
            raise

    LOGGER.info(
        "GCS to Google Drive transfer completed. Uploaded files: %d",
        len(uploaded_files),
    )
    return uploaded_files


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    transfer_gcs_to_google_drive()
