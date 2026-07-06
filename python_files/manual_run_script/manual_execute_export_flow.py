"""Execute the manual BigQuery to GCS to Google Drive flow."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence


# =============================================================================
# Project import path setup
# =============================================================================

SCRIPT_FOLDER = Path(__file__).resolve().parent
PYTHON_FILES_FOLDER = SCRIPT_FOLDER.parent

if str(PYTHON_FILES_FOLDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_FILES_FOLDER))


# =============================================================================
# Project imports
# =============================================================================

from manual_run_script.manual_bigquery_to_gcs import (
    DEFAULT_MANUAL_SQL_PATH,
    export_manual_bigquery_to_gcs,
)
from manual_run_script.manual_gcs_to_google_drive import (
    transfer_manual_gcs_to_google_drive,
)
from lark_notification import FAILED_STATUS
from lark_notification import SUCCESS_STATUS
from lark_notification import PipelineRunRecord
from lark_notification import send_lark_pipeline_notification


# =============================================================================
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Public manual flow function
# =============================================================================

def execute_manual_export_flow(
    country_code: str,
    year_id: int,
    month_id: int,
    sql_path: Path = DEFAULT_MANUAL_SQL_PATH,
) -> list[dict[str, str]]:
    """Run the manual export, then upload the exported GCS file to Drive."""

    bq_to_gcs_status = FAILED_STATUS
    gcs_to_gdrive_status = FAILED_STATUS
    error_reason = "-"

    try:
        # ---------------------------------------------------------------------
        # Export the parameterized BigQuery query and capture the final GCS URI.
        # ---------------------------------------------------------------------

        exported_gcs_uri = export_manual_bigquery_to_gcs(
            country_code=country_code,
            year_id=year_id,
            month_id=month_id,
            sql_path=sql_path,
        )
        bq_to_gcs_status = SUCCESS_STATUS
        LOGGER.info("Manual export completed at: %s", exported_gcs_uri)

        # ---------------------------------------------------------------------
        # Upload the exported GCS object to the configured Google Drive folder.
        # ---------------------------------------------------------------------

        uploaded_files = transfer_manual_gcs_to_google_drive(
            gcs_uri=exported_gcs_uri,
            country_code=country_code,
            year_id=year_id,
            month_id=month_id,
        )
        gcs_to_gdrive_status = SUCCESS_STATUS
        for uploaded_file in uploaded_files:
            LOGGER.info(
                "Manual flow uploaded %s to Google Drive: %s",
                uploaded_file["gcs_uri"],
                uploaded_file["drive_url"],
            )

        return uploaded_files
    except Exception as error:
        error_reason = f"{type(error).__name__}: {error}"
        raise
    finally:
        # ---------------------------------------------------------------------
        # Notify Lark with the final step-level status for this manual run.
        # ---------------------------------------------------------------------

        send_lark_pipeline_notification(
            run_type="Manual run",
            records=[
                PipelineRunRecord(
                    country_code=country_code,
                    year_id=year_id,
                    month_id=month_id,
                    bq_to_gcs_status=bq_to_gcs_status,
                    gcs_to_gdrive_status=gcs_to_gdrive_status,
                    error_reason=error_reason,
                )
            ],
        )


# =============================================================================
# Command line interface
# =============================================================================

def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse manual export flow parameters from the command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the manual BigQuery export and upload the resulting GCS file "
            "to Google Drive."
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
    """Run the complete manual export flow from command-line arguments."""

    arguments = _parse_arguments(argv)
    execute_manual_export_flow(
        country_code=arguments.country_code,
        year_id=arguments.year_id,
        month_id=arguments.month_id,
        sql_path=Path(arguments.sql_path),
    )


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
