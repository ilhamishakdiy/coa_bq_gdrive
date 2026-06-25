"""Export BigQuery data to Google Cloud Storage."""

# =============================================================================
# Library imports
# =============================================================================

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =============================================================================
# Third-party imports
# =============================================================================

from dotenv import load_dotenv
from google import auth
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery
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
# Public export function
# =============================================================================

def export_bigquery_to_gcs() -> list[str]:
    """Export every configured query and return generated GCS wildcard URIs."""

    # -------------------------------------------------------------------------
    # Load runtime configuration and create the BigQuery client.
    # -------------------------------------------------------------------------

    bigquery_project_id = _project_environment_value("BQ_PROJECT_ID")
    bucket_name = _required_environment_value("GCS_BUCKET_NAME")
    credentials_path = _optional_environment_value(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    bigquery_location = _optional_environment_value("BQ_LOCATION")

    credentials = _load_credentials(credentials_path)
    client = bigquery.Client(
        project=bigquery_project_id,
        credentials=credentials,
    )

    # -------------------------------------------------------------------------
    # Build and execute the BigQuery EXPORT DATA statement.
    # -------------------------------------------------------------------------

    source_queries = _build_source_queries()
    csv_delimiter = _csv_delimiter()
    escaped_delimiter = csv_delimiter.replace("\\", "\\\\").replace("'", "\\'")
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exported_uris: list[str] = []

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
        export_statement = f"""
            EXPORT DATA OPTIONS (
                uri = '{escaped_uri}',
                format = 'CSV',
                field_delimiter = '{escaped_delimiter}',
                overwrite = false,
                header = true
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
            query_job = client.query(
                export_statement,
                location=bigquery_location,
            )
            query_job.result()
            exported_uris.append(gcs_export_uri)
            LOGGER.info(
                "Export %s completed successfully. Job ID: %s",
                export_name,
                query_job.job_id,
            )
        except GoogleAPIError:
            LOGGER.exception("BigQuery export failed for %s", export_name)
            raise

    return exported_uris


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    exported_uris = export_bigquery_to_gcs()
    for exported_uri in exported_uris:
        LOGGER.info("Exported GCS URI: %s", exported_uri)
