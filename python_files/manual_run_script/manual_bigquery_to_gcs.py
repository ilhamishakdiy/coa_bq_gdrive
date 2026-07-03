"""Run a parameterized manual BigQuery extract to Google Cloud Storage."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Sequence
from uuid import uuid4


# =============================================================================
# Project import path setup
# =============================================================================

SCRIPT_FOLDER = Path(__file__).resolve().parent
PYTHON_FILES_FOLDER = SCRIPT_FOLDER.parent
PROJECT_ROOT = PYTHON_FILES_FOLDER.parent

if str(PYTHON_FILES_FOLDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_FILES_FOLDER))


# =============================================================================
# Third-party imports
# =============================================================================

from dotenv import load_dotenv
from google import auth
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery, storage
from google.oauth2 import service_account


# =============================================================================
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
load_dotenv(PROJECT_ROOT / ".env", override=False)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MANUAL_SQL_PATH = PROJECT_ROOT / "sql" / "manual_run.sql"
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MAXIMUM_COMPOSE_SOURCES = 32


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
            scopes=(GOOGLE_CLOUD_SCOPE,),
        )

    # -------------------------------------------------------------------------
    # Use Application Default Credentials in managed Google environments.
    # -------------------------------------------------------------------------

    credentials, _ = auth.default(scopes=(GOOGLE_CLOUD_SCOPE,))
    return credentials


# =============================================================================
# Parameter validation
# =============================================================================

def _validate_country_code(country_code: str) -> str:
    """Return a safe country code for the SQL template."""

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


# =============================================================================
# SQL template handling
# =============================================================================

def _read_manual_sql_template(sql_path: Path) -> str:
    """Read the manual SQL template from disk."""

    resolved_sql_path = sql_path.expanduser()
    if not resolved_sql_path.is_absolute():
        resolved_sql_path = PROJECT_ROOT / resolved_sql_path

    if not resolved_sql_path.is_file():
        raise FileNotFoundError(
            f"Manual SQL file was not found: {resolved_sql_path}"
        )

    sql_template = resolved_sql_path.read_text(encoding="utf-8").strip()
    if not sql_template:
        raise ValueError(f"Manual SQL file is empty: {resolved_sql_path}")

    return sql_template.rstrip(";")


def _render_manual_sql(
    country_code: str,
    year_id: int,
    month_id: int,
    sql_path: Path,
) -> str:
    """Apply COUNTRYCODE, YEARID, and MONTHID to the SQL template."""

    safe_country_code = _validate_country_code(country_code)
    safe_year_id = _validate_year_id(year_id)
    safe_month_id = _validate_month_id(month_id)
    sql_template = _read_manual_sql_template(sql_path)

    required_tokens = ("{COUNTRYCODE}", "{YEARID}", "{MONTHID}")
    missing_tokens = [
        token
        for token in required_tokens
        if token not in sql_template
    ]
    if missing_tokens:
        raise ValueError(
            "Manual SQL template is missing required parameter token(s): "
            f"{', '.join(missing_tokens)}"
        )

    return sql_template.format(
        COUNTRYCODE=safe_country_code,
        YEARID=safe_year_id,
        MONTHID=safe_month_id,
    )


# =============================================================================
# BigQuery export and GCS URI helpers
# =============================================================================

def _build_bucket_file_name(
    country_code: str,
    year_id: int,
    month_id: int,
    run_timestamp: str,
) -> str:
    """Build the timestamped CSV filename used in the GCS bucket."""

    safe_country_code = _validate_country_code(country_code)
    safe_year_id = _validate_year_id(year_id)
    safe_month_id = _validate_month_id(month_id)
    return (
        "STORE_SKU_SALES_MONTH_"
        f"{safe_country_code}_{safe_month_id:02d}{safe_year_id}_"
        f"{run_timestamp}.csv"
    )


def _build_gcs_export_uri(
    bucket_name: str,
    bucket_file_name: str,
    country_code: str,
) -> str:
    """Return the configured URI or generate a Drive-compatible wildcard URI."""

    safe_country_code = _validate_country_code(country_code)
    bucket_file_stem = Path(bucket_file_name).stem
    configured_uri = _optional_environment_value("GCS_EXPORT_URI")
    if configured_uri:
        _validate_gcs_export_uri(configured_uri, bucket_name)
        _, configured_object_name = _split_gcs_uri(configured_uri)
        configured_parent = Path(configured_object_name).parent.as_posix()
        configured_prefix = "" if configured_parent == "." else configured_parent
        configured_object_path = "/".join(
            part
            for part in (configured_prefix, f"{bucket_file_stem}_*.csv")
            if part
        )
        return f"gs://{bucket_name}/{configured_object_path}"

    object_prefix = os.getenv(
        "GCS_OBJECT_PREFIX",
        "exports/bigquery",
    ).strip("/")

    object_name = f"{bucket_file_stem}_*.csv"
    object_path = "/".join(
        part for part in (object_prefix, safe_country_code, object_name) if part
    )
    return f"gs://{bucket_name}/{object_path}"


def _validate_gcs_export_uri(gcs_uri: str, expected_bucket: str) -> None:
    """Validate the Cloud Storage destination used by BigQuery."""

    uri_match = re.fullmatch(r"gs://([^/]+)/(.+)", gcs_uri)
    if not uri_match:
        raise ValueError("GCS_EXPORT_URI must use gs://bucket/object format.")

    bucket_name, object_name = uri_match.groups()
    if bucket_name != expected_bucket:
        raise ValueError("GCS_EXPORT_URI bucket must match GCS_BUCKET_NAME.")

    if "*" not in object_name:
        raise ValueError("GCS_EXPORT_URI must contain a wildcard (*).")


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
    source_parent = Path(wildcard_object_name).parent
    country_folder = source_parent.name
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
        for part in (destination_prefix, country_folder, composed_file_name)
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
    bucket: storage.Bucket,
    source_blobs: list[storage.Blob],
    destination_object_name: str,
    delete_source_objects: bool,
) -> storage.Blob:
    """Compose up to 32 GCS objects into one object."""

    if not 1 <= len(source_blobs) <= MAXIMUM_COMPOSE_SOURCES:
        raise ValueError(
            "A GCS compose request requires between 1 and 32 source objects."
        )

    destination_blob = bucket.blob(destination_object_name)
    destination_blob.compose(
        source_blobs,
        if_generation_match=0,
    )
    destination_blob.reload()

    # -------------------------------------------------------------------------
    # Delete inputs only after the composed output exists.
    # -------------------------------------------------------------------------

    if delete_source_objects:
        for source_blob in source_blobs:
            source_blob.delete()

    LOGGER.info(
        "Composed %d objects into gs://%s/%s",
        len(source_blobs),
        bucket.name,
        destination_object_name,
    )
    return destination_blob


def _compose_export_shards(
    storage_client: storage.Client,
    gcs_export_uri: str,
    csv_header: bytes,
    delete_source_objects: bool,
) -> str:
    """Recursively compose all export shards and return one exact GCS URI."""

    # -------------------------------------------------------------------------
    # Upload only the small header object; shard data never passes through VM.
    # -------------------------------------------------------------------------

    bucket_name, wildcard_object_name = _split_gcs_uri(gcs_export_uri)
    bucket = storage_client.bucket(bucket_name)
    destination_object_name = _build_composed_object_name(wildcard_object_name)
    destination_blob = bucket.blob(destination_object_name)

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
    header_blob = bucket.blob(f"{temporary_prefix}/header.csv")
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

            if len(source_group) == 1:
                next_level_blobs.append(source_group[0])
                continue

            temporary_object_name = (
                f"{temporary_prefix}/level_{compose_level:03d}_"
                f"group_{group_index:06d}.csv"
            )
            next_level_blobs.append(
                _compose_objects(
                    bucket=bucket,
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
        bucket=bucket,
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
# Public manual export function
# =============================================================================

def export_manual_bigquery_to_gcs(
    country_code: str,
    year_id: int,
    month_id: int,
    sql_path: Path = DEFAULT_MANUAL_SQL_PATH,
) -> str:
    """Export one manual parameterized BigQuery query to GCS."""

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
    # Render the SQL template and prepare the GCS export destination.
    # -------------------------------------------------------------------------

    source_query = _render_manual_sql(
        country_code=country_code,
        year_id=year_id,
        month_id=month_id,
        sql_path=sql_path,
    )
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bucket_file_name = _build_bucket_file_name(
        country_code=country_code,
        year_id=year_id,
        month_id=month_id,
        run_timestamp=run_timestamp,
    )
    csv_delimiter = _csv_delimiter()
    escaped_delimiter = csv_delimiter.replace("\\", "\\\\").replace("'", "\\'")
    gcs_export_uri = _build_gcs_export_uri(
        bucket_name=bucket_name,
        bucket_file_name=bucket_file_name,
        country_code=country_code,
    )
    escaped_uri = gcs_export_uri.replace("\\", "\\\\").replace("'", "\\'")

    # -------------------------------------------------------------------------
    # Run BigQuery EXPORT DATA and write CSV shards into Cloud Storage.
    # -------------------------------------------------------------------------

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
            "Starting manual export for COUNTRYCODE=%s, YEARID=%s, MONTHID=%s",
            _validate_country_code(country_code),
            _validate_year_id(year_id),
            _validate_month_id(month_id),
        )
        query_job = query_client.query(
            export_statement,
            location=bigquery_location,
        )
        query_job.result()
        LOGGER.info(
            "Manual export completed successfully. Job ID: %s",
            query_job.job_id,
        )

        # ---------------------------------------------------------------------
        # Compose shards in GCS or return the wildcard URI when disabled.
        # ---------------------------------------------------------------------

        if compose_gcs_shards:
            return _compose_export_shards(
                storage_client=storage_client,
                gcs_export_uri=gcs_export_uri,
                csv_header=csv_header,
                delete_source_objects=delete_source_objects,
            )

        return gcs_export_uri
    except GoogleAPIError:
        LOGGER.exception("Manual BigQuery export failed.")
        raise


# =============================================================================
# Command line interface
# =============================================================================

def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse manual-run parameters from the command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Export sql/manual_run.sql to GCS using COUNTRYCODE, YEARID, "
            "and MONTHID parameters."
        )
    )
    parser.add_argument(
        "--countrycode",
        "--country-code",
        dest="country_code",
        required=True,
        help="Country code to pass into {COUNTRYCODE}.",
    )
    parser.add_argument(
        "--yearid",
        "--year-id",
        dest="year_id",
        required=True,
        type=int,
        help="Year ID to pass into {YEARID}.",
    )
    parser.add_argument(
        "--monthid",
        "--month-id",
        dest="month_id",
        required=True,
        type=int,
        help="Month ID to pass into {MONTHID}.",
    )
    parser.add_argument(
        "--sql-path",
        default=str(DEFAULT_MANUAL_SQL_PATH),
        help="Path to the manual SQL template.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the manual export from command-line arguments."""

    arguments = _parse_arguments(argv)
    exported_uri = export_manual_bigquery_to_gcs(
        country_code=arguments.country_code,
        year_id=arguments.year_id,
        month_id=arguments.month_id,
        sql_path=Path(arguments.sql_path),
    )
    LOGGER.info("Manual export GCS URI: %s", exported_uri)


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
