"""Export BigQuery data and compose its CSV shards inside Cloud Storage."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import csv
import fnmatch
import io
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4


# =============================================================================
# Third-party imports
# =============================================================================

from dotenv import load_dotenv
from google import auth
from google.api_core import exceptions
from google.api_core.exceptions import GoogleAPIError
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery, storage
from google.oauth2 import service_account


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

GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MAXIMUM_COMPOSE_SOURCES = 32
GCS_JSON_API_BASE_URL = "https://storage.googleapis.com/storage/v1"


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


def _csv_delimiter() -> str:
    """Return the configured single-character CSV field delimiter."""

    configured_delimiter = os.getenv("CSV_DELIMITER", ",")
    delimiter = "\t" if configured_delimiter == r"\t" else configured_delimiter

    if len(delimiter) != 1:
        raise ValueError(
            "CSV_DELIMITER must contain exactly one character, such as , ; | "
            r"or \t."
        )

    return delimiter


# =============================================================================
# Boolean configuration helpers
# =============================================================================

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


# =============================================================================
# Authentication
# =============================================================================

def _load_credentials(credentials_path: str | None) -> Any:
    """Load a service-account key or Application Default Credentials."""

    # -------------------------------------------------------------------------
    # Use the service-account key configured in .env 
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
            scopes=(GOOGLE_CLOUD_SCOPE,),
        )

    # -------------------------------------------------------------------------
    # Use Application Default Credentials in managed Google environments.
    # -------------------------------------------------------------------------

    credentials, _ = auth.default(scopes=(GOOGLE_CLOUD_SCOPE,))
    return credentials


# =============================================================================
# BigQuery query and GCS URI helpers
# =============================================================================

def _safe_export_name(value: str) -> str:
    """Convert a SQL filename or table name into a safe object-name segment."""

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    if not safe_name:
        raise ValueError(f"Cannot create an export name from: {value}")
    return safe_name


def _build_source_queries() -> list[tuple[str, str]]:
    """Read every SQL query from the configured folder."""

    sql_folder = _required_environment_value("BQ_SQL_FOLDER")

    # -------------------------------------------------------------------------
    # Read every .sql file from the configured project-relative folder.
    # -------------------------------------------------------------------------

    sql_folder_path = Path(sql_folder).expanduser()
    if not sql_folder_path.is_absolute():
        sql_folder_path = PROJECT_ROOT / sql_folder_path

    if not sql_folder_path.is_dir():
        raise FileNotFoundError(
            f"BigQuery SQL folder was not found: {sql_folder_path}"
        )

    sql_paths = sorted(sql_folder_path.glob("*.sql"))
    if not sql_paths:
        raise FileNotFoundError(
            f"No .sql files were found in: {sql_folder_path}"
        )

    source_queries: list[tuple[str, str]] = []
    for sql_path in sql_paths:
        sql_query = sql_path.read_text(encoding="utf-8").strip().rstrip(";")
        if not sql_query:
            raise ValueError(f"BigQuery SQL file is empty: {sql_path}")

        source_queries.append(
            (_safe_export_name(sql_path.stem), sql_query)
        )

    return source_queries


def _build_gcs_export_uri(
    bucket_name: str,
    export_name: str,
    run_timestamp: str,
    export_count: int,
) -> str:
    """Return the configured URI or generate a timestamped wildcard URI."""

    configured_uri = _optional_environment_value("GCS_EXPORT_URI")
    if configured_uri:
        _validate_gcs_export_uri(configured_uri, bucket_name)
        if export_count > 1:
            return configured_uri.replace(
                "*",
                f"{export_name}_*",
                1,
            )
        return configured_uri

    object_prefix = os.getenv(
        "GCS_OBJECT_PREFIX",
        "exports/bigquery",
    ).strip("/")
    file_name = os.getenv("EXPORT_FILE_NAME", "bigquery_export").strip()
    if not file_name:
        raise ValueError("EXPORT_FILE_NAME cannot be empty.")

    object_name = f"{file_name}_{export_name}_{run_timestamp}_*.csv"
    object_path = "/".join(
        part for part in (object_prefix, object_name) if part
    )
    return f"gs://{bucket_name}/{object_path}"


def _validate_gcs_export_uri(gcs_uri: str, expected_bucket: str) -> None:
    """Validate the Cloud Storage destination used by BigQuery."""

    uri_match = re.fullmatch(r"gs://([^/]+)/(.+)", gcs_uri)
    if not uri_match:
        raise ValueError("GCS_EXPORT_URI must use gs://bucket/object format.")

    bucket_name, object_name = uri_match.groups()
    if bucket_name != expected_bucket:
        raise ValueError(
            "GCS_EXPORT_URI bucket must match GCS_BUCKET_NAME."
        )

    if "*" not in object_name:
        raise ValueError("GCS_EXPORT_URI must contain a wildcard (*).")


# =============================================================================
# GCS object-name and CSV header helpers
# =============================================================================

def _split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """Split a GCS URI into bucket and object-name components."""

    uri_match = re.fullmatch(r"gs://([^/]+)/(.+)", gcs_uri)
    if not uri_match:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")

    return uri_match.group(1), uri_match.group(2)


def _build_composed_object_name(wildcard_object_name: str) -> str:
    """Build the final CSV object name under the configured merged prefix."""

    destination_prefix = os.getenv(
        "GCS_MERGED_OBJECT_PREFIX",
        "exports/bigquery_merged",
    ).strip("/")
    source_file_name = Path(wildcard_object_name).name

    # -------------------------------------------------------------------------
    # Remove the separator before the wildcard for a clean final filename.
    # -------------------------------------------------------------------------

    if source_file_name.endswith("_*.csv"):
        composed_file_name = f"{source_file_name[:-6]}.csv"
    else:
        composed_file_name = source_file_name.replace("*", "composed", 1)

    return "/".join(
        part
        for part in (destination_prefix, composed_file_name)
        if part
    )


def _build_csv_header(
    query_client: bigquery.Client,
    source_query: str,
    csv_delimiter: str,
    bigquery_location: str | None,
) -> bytes:
    """Build one CSV header row from the source query schema."""

    # -------------------------------------------------------------------------
    # Use a dry run so BigQuery validates the query without scanning result data.
    # -------------------------------------------------------------------------

    dry_run_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
    )
    dry_run_job = query_client.query(
        source_query,
        job_config=dry_run_config,
        location=bigquery_location,
    )
    field_names = [field.name for field in dry_run_job.schema]

    if not field_names:
        raise ValueError("The BigQuery query did not return any CSV columns.")

    # -------------------------------------------------------------------------
    # Serialize the schema with standard CSV quoting and one newline terminator.
    # -------------------------------------------------------------------------

    header_stream = io.StringIO(newline="")
    writer = csv.writer(
        header_stream,
        delimiter=csv_delimiter,
        lineterminator="\n",
    )
    writer.writerow(field_names)
    return header_stream.getvalue().encode("utf-8")


def _list_export_shards(
    storage_client: storage.Client,
    gcs_export_uri: str,
) -> list[storage.Blob]:
    """List every exported object matching the wildcard GCS URI."""

    bucket_name, wildcard_object_name = _split_gcs_uri(gcs_export_uri)
    object_prefix = wildcard_object_name.split("*", maxsplit=1)[0]
    matching_blobs = [
        blob
        for blob in storage_client.list_blobs(
            bucket_name,
            prefix=object_prefix,
        )
        if fnmatch.fnmatchcase(blob.name, wildcard_object_name)
    ]

    if not matching_blobs:
        raise FileNotFoundError(
            f"No BigQuery export shards matched: {gcs_export_uri}"
        )

    return sorted(matching_blobs, key=lambda blob: blob.name)


# =============================================================================
# Server-side GCS composition
# =============================================================================

def _compose_objects(
    authorized_session: AuthorizedSession,
    bucket_name: str,
    source_blobs: list[storage.Blob],
    destination_object_name: str,
    delete_source_objects: bool,
) -> storage.Blob:
    """Compose up to 32 objects without streaming contents through Python."""

    if not 1 <= len(source_blobs) <= MAXIMUM_COMPOSE_SOURCES:
        raise ValueError(
            "A GCS compose request requires between 1 and 32 source objects."
        )

    # -------------------------------------------------------------------------
    # Pin every source generation so retries cannot combine changed objects.
    # -------------------------------------------------------------------------

    source_objects = []
    for source_blob in source_blobs:
        if source_blob.generation is None:
            source_blob.reload()

        source_objects.append(
            {
                "name": source_blob.name,
                "generation": str(source_blob.generation),
            }
        )

    encoded_bucket_name = quote(bucket_name, safe="")
    encoded_destination_name = quote(destination_object_name, safe="")
    compose_url = (
        f"{GCS_JSON_API_BASE_URL}/b/{encoded_bucket_name}/o/"
        f"{encoded_destination_name}/compose"
    )
    response = authorized_session.post(
        compose_url,
        params={"ifGenerationMatch": "0"},
        json={
            "sourceObjects": source_objects,
            "destination": {
                "contentType": "text/csv",
            },
            "deleteSourceObjects": delete_source_objects,
        },
        timeout=300,
    )

    if not response.ok:
        raise exceptions.from_http_response(response)

    destination_blob = source_blobs[0].bucket.blob(
        destination_object_name,
    )
    destination_blob.reload()
    LOGGER.info(
        "Composed %d objects into gs://%s/%s",
        len(source_blobs),
        bucket_name,
        destination_object_name,
    )
    return destination_blob


def _compose_export_shards(
    storage_client: storage.Client,
    credentials: Any,
    gcs_export_uri: str,
    csv_header: bytes,
    delete_source_objects: bool,
) -> str:
    """Recursively compose all export shards and return one exact GCS URI."""

    # -------------------------------------------------------------------------
    # Upload only the small header object; shard data never passes through VM.
    # -------------------------------------------------------------------------

    bucket_name, wildcard_object_name = _split_gcs_uri(gcs_export_uri)
    destination_object_name = _build_composed_object_name(
        wildcard_object_name
    )
    destination_blob = storage_client.bucket(bucket_name).blob(
        destination_object_name
    )

    if destination_blob.exists():
        raise FileExistsError(
            "Composed destination already exists: "
            f"gs://{bucket_name}/{destination_object_name}"
        )

    compose_run_id = uuid4().hex
    source_parent = Path(wildcard_object_name).parent.as_posix()
    temporary_prefix = (
        f"{source_parent}/.compose/{compose_run_id}"
    ).lstrip("./")
    header_blob = storage_client.bucket(bucket_name).blob(
        f"{temporary_prefix}/header.csv"
    )
    header_blob.upload_from_string(
        csv_header,
        content_type="text/csv",
        if_generation_match=0,
    )
    header_blob.reload()

    current_blobs = [
        header_blob,
        *_list_export_shards(storage_client, gcs_export_uri),
    ]
    authorized_session = AuthorizedSession(credentials)
    compose_level = 0

    LOGGER.info(
        "Starting server-side composition of %d objects for %s",
        len(current_blobs),
        gcs_export_uri,
    )

    # -------------------------------------------------------------------------
    # Reduce groups of 32 into temporary objects until one final group fits.
    # -------------------------------------------------------------------------

    while len(current_blobs) > MAXIMUM_COMPOSE_SOURCES:
        next_level_blobs: list[storage.Blob] = []

        for group_index, group_start in enumerate(
            range(0, len(current_blobs), MAXIMUM_COMPOSE_SOURCES)
        ):
            source_group = current_blobs[
                group_start:group_start + MAXIMUM_COMPOSE_SOURCES
            ]

            # -----------------------------------------------------------------
            # Carry a final single object forward instead of copying it.
            # -----------------------------------------------------------------

            if len(source_group) == 1:
                next_level_blobs.append(source_group[0])
                continue

            temporary_object_name = (
                f"{temporary_prefix}/level_{compose_level:03d}_"
                f"group_{group_index:06d}.csv"
            )
            next_level_blobs.append(
                _compose_objects(
                    authorized_session=authorized_session,
                    bucket_name=bucket_name,
                    source_blobs=source_group,
                    destination_object_name=temporary_object_name,
                    delete_source_objects=delete_source_objects,
                )
            )

        current_blobs = next_level_blobs
        compose_level += 1

    # -------------------------------------------------------------------------
    # Compose the last group into the stable final destination object.
    # -------------------------------------------------------------------------

    _compose_objects(
        authorized_session=authorized_session,
        bucket_name=bucket_name,
        source_blobs=current_blobs,
        destination_object_name=destination_object_name,
        delete_source_objects=delete_source_objects,
    )

    destination_gcs_uri = f"gs://{bucket_name}/{destination_object_name}"
    LOGGER.info(
        "Server-side GCS composition completed: %s",
        destination_gcs_uri,
    )
    return destination_gcs_uri


# =============================================================================
# Public export function
# =============================================================================

def export_bigquery_to_gcs() -> list[str]:
    """Export queries and return composed or wildcard GCS URIs."""

    # -------------------------------------------------------------------------
    # Load runtime configuration and create Google Cloud clients.
    # -------------------------------------------------------------------------

    bigquery_project_id = _project_environment_value("BQ_PROJECT_ID")
    gcs_project_id = _project_environment_value("GCS_PROJECT_ID")
    bucket_name = _required_environment_value("GCS_BUCKET_NAME")
    credentials_path = _optional_environment_value(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    bigquery_location = _optional_environment_value("BQ_LOCATION")
    compose_gcs_shards = _environment_boolean(
        "COMPOSE_GCS_SHARDS",
        default=True,
    )
    delete_source_objects = _environment_boolean(
        "DELETE_GCS_SOURCES_AFTER_COMPOSE",
        default=True,
    )

    credentials = _load_credentials(credentials_path)
    query_client = bigquery.Client(
        project=bigquery_project_id,
        credentials=credentials,
    )
    storage_client = storage.Client(
        project=gcs_project_id,
        credentials=credentials,
    )

    # -------------------------------------------------------------------------
    # Build and execute the BigQuery EXPORT DATA statement.
    # -------------------------------------------------------------------------

    source_queries = _build_source_queries()
    csv_delimiter = _csv_delimiter()
    escaped_delimiter = csv_delimiter.replace("\\", "\\\\").replace("'", "\\'")
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_uris: list[str] = []

    # -------------------------------------------------------------------------
    # Export each SQL file independently using its filename in the GCS path.
    # -------------------------------------------------------------------------

    for export_name, source_query in source_queries:
        gcs_export_uri = _build_gcs_export_uri(
            bucket_name=bucket_name,
            export_name=export_name,
            run_timestamp=run_timestamp,
            export_count=len(source_queries),
        )
        escaped_uri = gcs_export_uri.replace("\\", "\\\\").replace("'", "\\'")
        csv_header = _build_csv_header(
            query_client=query_client,
            source_query=source_query,
            csv_delimiter=csv_delimiter,
            bigquery_location=bigquery_location,
        )
        export_statement = f"""
            EXPORT DATA OPTIONS (
                uri = '{escaped_uri}',
                format = 'CSV',
                field_delimiter = '{escaped_delimiter}',
                overwrite = false,
                header = false
            ) AS
            {source_query}
        """

        try:
            LOGGER.info(
                "Starting export %s to %s using delimiter %r",
                export_name,
                gcs_export_uri,
                csv_delimiter,
            )
            query_job = query_client.query(
                export_statement,
                location=bigquery_location,
            )
            query_job.result()
            LOGGER.info(
                "Export %s completed successfully. Job ID: %s",
                export_name,
                query_job.job_id,
            )

            # -----------------------------------------------------------------
            # Compose shards in GCS or retain the wildcard URI when disabled.
            # -----------------------------------------------------------------

            if compose_gcs_shards:
                output_uri = _compose_export_shards(
                    storage_client=storage_client,
                    credentials=credentials,
                    gcs_export_uri=gcs_export_uri,
                    csv_header=csv_header,
                    delete_source_objects=delete_source_objects,
                )
            else:
                output_uri = gcs_export_uri

            output_uris.append(output_uri)
        except GoogleAPIError:
            LOGGER.exception("BigQuery export failed for %s", export_name)
            raise

    return output_uris


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    exported_uris = export_bigquery_to_gcs()
    for exported_uri in exported_uris:
        LOGGER.info("Exported GCS URI: %s", exported_uri)
