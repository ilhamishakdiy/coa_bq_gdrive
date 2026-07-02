"""Execute the scheduled BigQuery to GCS to Google Drive flow."""

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

from schedule_run_script.schedule_bigquery_to_gcs import (
    DEFAULT_SCHEDULE_SQL_PATH,
    export_schedule_bigquery_to_gcs,
)
from schedule_run_script.schedule_gcs_to_google_drive import (
    transfer_schedule_gcs_to_google_drive,
)


# =============================================================================
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Public scheduled flow function
# =============================================================================

def execute_schedule_export_flow(
    country_code: str,
    sql_path: Path = DEFAULT_SCHEDULE_SQL_PATH,
) -> list[dict[str, str]]:
    """Run the scheduled export, then upload the exported GCS file to Drive."""

    # -------------------------------------------------------------------------
    # Export the scheduled BigQuery query and capture the final GCS URI.
    # -------------------------------------------------------------------------

    exported_gcs_uri = export_schedule_bigquery_to_gcs(
        country_code=country_code,
        sql_path=sql_path,
    )
    LOGGER.info("Scheduled export completed at: %s", exported_gcs_uri)

    # -------------------------------------------------------------------------
    # Upload the exported GCS object to the configured Google Drive folder.
    # -------------------------------------------------------------------------

    uploaded_files = transfer_schedule_gcs_to_google_drive(exported_gcs_uri)
    for uploaded_file in uploaded_files:
        LOGGER.info(
            "Scheduled flow uploaded %s to Google Drive: %s",
            uploaded_file["gcs_uri"],
            uploaded_file["drive_url"],
        )

    return uploaded_files


# =============================================================================
# Command line interface
# =============================================================================

def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse optional scheduled flow arguments from the command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the scheduled previous-month BigQuery export and upload the "
            "resulting GCS file to Google Drive."
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
        "--sql-path",
        default=str(DEFAULT_SCHEDULE_SQL_PATH),
        help="Path to the scheduled previous-month SQL file.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the complete scheduled export flow from command-line arguments."""

    arguments = _parse_arguments(argv)
    execute_schedule_export_flow(
        country_code=arguments.country_code,
        sql_path=Path(arguments.sql_path),
    )


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
