"""Transfer a scheduled GCS extract file to Google Drive."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import argparse
import fnmatch
import logging
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Sequence
from urllib.parse import quote


# =============================================================================
# Project import path setup
# =============================================================================

SCRIPT_FOLDER = Path(__file__).resolve().parent
PYTHON_FILES_FOLDER = SCRIPT_FOLDER.parent

if str(PYTHON_FILES_FOLDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_FILES_FOLDER))


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
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = PYTHON_FILES_FOLDER.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
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
    """Split a GCS URI into bucket and object-name components."""

    uri_match = re.fullmatch(r"gs://([^/]+)/(.+)", gcs_uri)
    if not uri_match:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    return uri_match.group(1), uri_match.group(2)


def _list_matching_blobs(
    storage_client: storage.Client,
    gcs_uri: str,
) -> list[storage.Blob]:
    """List GCS objects matching the supplied exact or wildcard URI."""

    bucket_name, object_name = _split_gcs_uri(gcs_uri)
    bucket = storage_client.bucket(bucket_name)

    # -------------------------------------------------------------------------
    # Resolve exact GCS objects without scanning the bucket.
    # -------------------------------------------------------------------------

    if "*" not in object_name:
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"No GCS object matched: {gcs_uri}")
        return [blob]

    # -------------------------------------------------------------------------
    # Resolve wildcard GCS objects using the fixed prefix before the wildcard.
    # -------------------------------------------------------------------------

    object_prefix = object_name.split("*", maxsplit=1)[0]
    matching_blobs = [
        blob
        for blob in storage_client.list_blobs(
            bucket_name,
            prefix=object_prefix,
        )
        if fnmatch.fnmatchcase(blob.name, object_name)
    ]

    if not matching_blobs:
        raise FileNotFoundError(f"No GCS objects matched: {gcs_uri}")

    return sorted(matching_blobs, key=lambda blob: blob.name)


def _discover_latest_merged_gcs_uri(
    storage_client: storage.Client,
    bucket_name: str,
) -> str:
    """Return the latest object under the configured merged-object folder."""

    # -------------------------------------------------------------------------
    # Limit discovery to a non-empty folder so the whole bucket is never used.
    # -------------------------------------------------------------------------

    merged_object_prefix = os.getenv(
        "GCS_MERGED_OBJECT_PREFIX",
        "exports/bigquery_merged",
    ).strip("/")
    if not merged_object_prefix:
        raise ValueError(
            "GCS_MERGED_OBJECT_PREFIX cannot be empty when discovering "
            "the latest Google Drive source file."
        )

    folder_prefix = f"{merged_object_prefix}/"
    candidate_blobs = [
        blob
        for blob in storage_client.list_blobs(
            bucket_name,
            prefix=folder_prefix,
        )
        if blob.name != folder_prefix
    ]

    if not candidate_blobs:
        raise FileNotFoundError(
            "No files were found under "
            f"gs://{bucket_name}/{folder_prefix}"
        )

    # -------------------------------------------------------------------------
    # Prefer GCS update time and use object name as a stable tie-breaker.
    # -------------------------------------------------------------------------

    latest_blob = max(
        candidate_blobs,
        key=lambda blob: (
            blob.updated
            or blob.time_created
            or datetime.min.replace(tzinfo=timezone.utc),
            blob.name,
        ),
    )
    latest_gcs_uri = f"gs://{bucket_name}/{latest_blob.name}"
    LOGGER.info("Discovered latest merged GCS file: %s", latest_gcs_uri)
    return latest_gcs_uri


# =============================================================================
# Public transfer function
# =============================================================================

def transfer_schedule_gcs_to_google_drive(
    gcs_uri: str | None = None,
) -> list[dict[str, str]]:
    """Transfer a scheduled GCS export URI to Google Drive."""

    # -------------------------------------------------------------------------
    # Resolve an explicit URI before discovering the latest merged GCS object.
    # -------------------------------------------------------------------------

    configured_bucket = _required_environment_value("GCS_BUCKET_NAME")
    drive_folder_id = _required_environment_value("DRIVE_FOLDER_ID")
    delete_after_upload = _environment_boolean(
        "DELETE_GCS_AFTER_DRIVE_UPLOAD",
        default=False,
    )
    stream_chunk_size = _stream_chunk_size()
    storage_client, drive_client = _create_clients()
    resolved_gcs_uri = (
        gcs_uri
        or _optional_environment_value("GCS_DRIVE_SOURCE_URI")
        or _discover_latest_merged_gcs_uri(
            storage_client=storage_client,
            bucket_name=configured_bucket,
        )
    )

    bucket_name, _ = _split_gcs_uri(resolved_gcs_uri)
    if bucket_name != configured_bucket:
        raise ValueError("The GCS URI bucket must match GCS_BUCKET_NAME.")

    # -------------------------------------------------------------------------
    # Stream each resolved GCS object directly into a resumable Drive upload.
    # -------------------------------------------------------------------------

    uploaded_files: list[dict[str, str]] = []
    for blob in _list_matching_blobs(storage_client, resolved_gcs_uri):
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
        "Scheduled GCS to Google Drive transfer completed. Uploaded files: %d",
        len(uploaded_files),
    )
    return uploaded_files


# =============================================================================
# Command line interface
# =============================================================================

def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the optional scheduled GCS URI from the command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Upload a scheduled GCS extract file to the configured Google "
            "Drive folder."
        )
    )
    parser.add_argument(
        "--gcs-uri",
        default=None,
        help=(
            "Exact or wildcard GCS URI to upload. When omitted, the shared "
            "GCS_DRIVE_SOURCE_URI/latest merged-object fallback is used."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the scheduled GCS-to-Google-Drive transfer."""

    arguments = _parse_arguments(argv)
    uploaded_files = transfer_schedule_gcs_to_google_drive(arguments.gcs_uri)

    # -------------------------------------------------------------------------
    # Log each uploaded Drive file for scheduled-run tracking.
    # -------------------------------------------------------------------------

    for uploaded_file in uploaded_files:
        LOGGER.info(
            "Uploaded %s to Google Drive: %s",
            uploaded_file["gcs_uri"],
            uploaded_file["drive_url"],
        )


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
