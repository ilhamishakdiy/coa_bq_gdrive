"""Run a parameterized manual BigQuery extract to Google Cloud Storage."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


# =============================================================================
# Project import path setup
# =============================================================================

SCRIPT_FOLDER = Path(__file__).resolve().parent
PYTHON_FILES_FOLDER = SCRIPT_FOLDER.parent
PROJECT_ROOT = PYTHON_FILES_FOLDER.parent

if str(PYTHON_FILES_FOLDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_FILES_FOLDER))


# =============================================================================
# Project imports
# =============================================================================

from bigquery_to_gcs import (  # noqa: E402
    _build_csv_header,
    _build_gcs_export_uri,
    _compose_export_shards,
    _csv_delimiter,
    _environment_boolean,
    _load_credentials,
    _optional_environment_value,
    _project_environment_value,
    _required_environment_value,
)
from google.api_core.exceptions import GoogleAPIError  # noqa: E402
from google.cloud import bigquery, storage  # noqa: E402


# =============================================================================
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_MANUAL_SQL_PATH = PROJECT_ROOT / "sql" / "manual_run.sql"
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


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
# Export naming
# =============================================================================

def _manual_export_name(
    country_code: str,
    year_id: int,
    month_id: int,
) -> str:
    """Build a stable export name that includes the manual-run parameters."""

    safe_country_code = _validate_country_code(country_code).lower()
    safe_year_id = _validate_year_id(year_id)
    safe_month_id = _validate_month_id(month_id)
    return f"manual_run_{safe_country_code}_{safe_year_id}_{safe_month_id:02d}"


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
    export_name = _manual_export_name(
        country_code=country_code,
        year_id=year_id,
        month_id=month_id,
    )
    csv_delimiter = _csv_delimiter()
    escaped_delimiter = csv_delimiter.replace("\\", "\\\\").replace("'", "\\'")
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gcs_export_uri = _build_gcs_export_uri(
        bucket_name=bucket_name,
        export_name=export_name,
        run_timestamp=run_timestamp,
        export_count=1,
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
                credentials=credentials,
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
