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
from datetime import date, datetime, timedelta, timezone
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
# Project imports
# =============================================================================

from pipeline_config import build_drive_file_name


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
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


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
# Parameter validation
# =============================================================================

def _validate_country_code(country_code: str) -> str:
    """Return a safe country code for Drive folder and file naming."""

    normalized_country_code = country_code.strip().upper()
    if not normalized_country_code:
        raise ValueError("COUNTRYCODE cannot be empty.")

    if not COUNTRY_CODE_PATTERN.fullmatch(normalized_country_code):
        raise ValueError(
            "COUNTRYCODE may contain only letters, numbers, underscores, "
            "and hyphens."
        )

    return normalized_country_code


def _validate_year_id(year_id: int) -> int:
    """Return a valid four-digit YEARID."""

    if year_id < 1900 or year_id > 9999:
        raise ValueError("YEARID must be a four-digit year.")
    return year_id


def _validate_month_id(month_id: int) -> int:
    """Return a valid MONTHID value."""

    if month_id < 1 or month_id > 12:
        raise ValueError("MONTHID must be between 1 and 12.")
    return month_id


def _previous_month_period(reference_date: date | None = None) -> tuple[int, int]:
    """Return YEARID and MONTHID for the previous calendar month."""

    current_date = reference_date or datetime.now(timezone.utc).date()
    previous_month_date = current_date.replace(day=1) - timedelta(days=1)
    return previous_month_date.year, previous_month_date.month


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
# Google Drive helpers
# =============================================================================

def _drive_query_literal(value: str) -> str:
    """Escape a string value for a Google Drive query literal."""

    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_or_create_drive_folder(
    drive_client: Any,
    parent_folder_id: str,
    folder_name: str,
) -> str:
    """Return a child Drive folder ID, creating the folder when needed."""

    escaped_parent_id = _drive_query_literal(parent_folder_id)
    escaped_folder_name = _drive_query_literal(folder_name)
    query = (
        f"name = '{escaped_folder_name}' "
        f"and mimeType = '{DRIVE_FOLDER_MIME_TYPE}' "
        f"and '{escaped_parent_id}' in parents "
        "and trashed = false"
    )
    folder_response = (
        drive_client.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    existing_folders = folder_response.get("files", [])

    # -------------------------------------------------------------------------
    # Reuse the first matching folder to keep reruns idempotent.
    # -------------------------------------------------------------------------

    if existing_folders:
        if len(existing_folders) > 1:
            LOGGER.warning(
                "Multiple Drive folders named %s were found. Using %s.",
                folder_name,
                existing_folders[0]["id"],
            )
        return existing_folders[0]["id"]

    # -------------------------------------------------------------------------
    # Create the country folder under the configured parent Drive folder.
    # -------------------------------------------------------------------------

    created_folder = (
        drive_client.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": DRIVE_FOLDER_MIME_TYPE,
                "parents": [parent_folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    LOGGER.info("Created Google Drive folder %s: %s", folder_name, created_folder["id"])
    return created_folder["id"]


def _build_drive_file_name(
    country_code: str,
    year_id: int,
    month_id: int,
) -> str:
    """Build the configured final Google Drive filename."""

    safe_country_code = _validate_country_code(country_code)
    safe_year_id = _validate_year_id(year_id)
    safe_month_id = _validate_month_id(month_id)
    return build_drive_file_name(
        country_code=safe_country_code,
        year_id=safe_year_id,
        month_id=safe_month_id,
    )


def _resolve_drive_destination(
    drive_client: Any,
    parent_folder_id: str,
    country_code: str | None,
    year_id: int | None,
    month_id: int | None,
) -> tuple[str, str | None]:
    """Return the target Drive folder and optional final filename."""

    if country_code is None and year_id is None and month_id is None:
        return parent_folder_id, None

    if country_code is None:
        raise ValueError(
            "COUNTRYCODE is required when overriding the scheduled Google "
            "Drive folder and filename."
        )

    if year_id is None and month_id is None:
        year_id, month_id = _previous_month_period()
    elif year_id is None or month_id is None:
        raise ValueError(
            "YEARID and MONTHID must be provided together for scheduled "
            "Google Drive filename overrides."
        )

    safe_country_code = _validate_country_code(country_code)
    country_folder_id = _find_or_create_drive_folder(
        drive_client=drive_client,
        parent_folder_id=parent_folder_id,
        folder_name=safe_country_code,
    )
    drive_file_name = _build_drive_file_name(
        country_code=safe_country_code,
        year_id=year_id,
        month_id=month_id,
    )
    return country_folder_id, drive_file_name


# =============================================================================
# Public transfer function
# =============================================================================

def transfer_schedule_gcs_to_google_drive(
    gcs_uri: str | None = None,
    country_code: str | None = None,
    year_id: int | None = None,
    month_id: int | None = None,
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

    target_drive_folder_id, target_file_name = _resolve_drive_destination(
        drive_client=drive_client,
        parent_folder_id=drive_folder_id,
        country_code=country_code,
        year_id=year_id,
        month_id=month_id,
    )

    # -------------------------------------------------------------------------
    # Stream each resolved GCS object directly into a resumable Drive upload.
    # -------------------------------------------------------------------------

    uploaded_files: list[dict[str, str]] = []
    for blob in _list_matching_blobs(storage_client, resolved_gcs_uri):
        file_name = target_file_name or Path(blob.name).name
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
                            "parents": [target_drive_folder_id],
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
                    "drive_file_name": file_name,
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
    parser.add_argument(
        "--countrycode",
        "--country-code",
        dest="country_code",
        default=None,
        help="Country code used for the Drive child folder and final filename.",
    )
    parser.add_argument(
        "--yearid",
        "--year-id",
        dest="year_id",
        default=None,
        type=int,
        help=(
            "Optional year ID used for the final Drive filename. When omitted "
            "with MONTHID, the previous calendar month is used."
        ),
    )
    parser.add_argument(
        "--monthid",
        "--month-id",
        dest="month_id",
        default=None,
        type=int,
        help=(
            "Optional month ID used for the final Drive filename. When omitted "
            "with YEARID, the previous calendar month is used."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the scheduled GCS-to-Google-Drive transfer."""

    arguments = _parse_arguments(argv)
    uploaded_files = transfer_schedule_gcs_to_google_drive(
        gcs_uri=arguments.gcs_uri,
        country_code=arguments.country_code,
        year_id=arguments.year_id,
        month_id=arguments.month_id,
    )

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
