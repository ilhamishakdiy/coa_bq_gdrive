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
from types import TracebackType
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

from schedule_run_script.schedule_bigquery_to_gcs import (
    DEFAULT_SCHEDULE_SQL_PATH,
    export_schedule_bigquery_to_gcs,
)
from schedule_run_script.schedule_gcs_to_google_drive import (
    _previous_month_period,
    transfer_schedule_gcs_to_google_drive,
)
from lark_notification import FAILED_STATUS
from lark_notification import SUCCESS_STATUS
from lark_notification import PipelineRunRecord
from lark_notification import send_lark_pipeline_notification


# =============================================================================
# Country-code file helpers
# =============================================================================

def _read_country_code_file(country_code_file: Path) -> list[str]:
    """Read country codes from a text file for scheduled batch runs."""

    resolved_path = country_code_file.expanduser()
    if not resolved_path.is_absolute():
        resolved_path = PROJECT_ROOT / resolved_path

    if not resolved_path.is_file():
        raise FileNotFoundError(f"Country-code file was not found: {resolved_path}")

    country_codes: list[str] = []
    for line_number, raw_line in enumerate(
        resolved_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line_without_comment = raw_line.split("#", maxsplit=1)[0].strip()
        if not line_without_comment:
            continue

        line_country_codes: list[str] = []
        for raw_country_code in line_without_comment.split(","):
            country_code = raw_country_code.strip()
            if country_code:
                line_country_codes.append(country_code)

        if not line_country_codes:
            raise ValueError(
                "Country-code file contains no valid country code on line "
                f"{line_number}: {raw_line}"
            )

        country_codes.extend(line_country_codes)

    if not country_codes:
        raise ValueError(f"Country-code file is empty: {resolved_path}")

    return country_codes


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

def _run_schedule_export_steps(
    country_code: str,
    sql_path: Path = DEFAULT_SCHEDULE_SQL_PATH,
) -> tuple[list[dict[str, str]], PipelineRunRecord, BaseException | None]:
    """Run one scheduled country export and return its notification record."""

    year_id, month_id = _previous_month_period()
    bq_to_gcs_status = FAILED_STATUS
    gcs_to_gdrive_status = FAILED_STATUS
    error_reason = "-"
    uploaded_files: list[dict[str, str]] = []
    caught_error: BaseException | None = None

    try:
        # ---------------------------------------------------------------------
        # Export the scheduled BigQuery query and capture the final GCS URI.
        # ---------------------------------------------------------------------

        exported_gcs_uri = export_schedule_bigquery_to_gcs(
            country_code=country_code,
            sql_path=sql_path,
        )
        bq_to_gcs_status = SUCCESS_STATUS
        LOGGER.info("Scheduled export completed at: %s", exported_gcs_uri)

        # ---------------------------------------------------------------------
        # Upload the exported GCS object to the configured Google Drive folder.
        # ---------------------------------------------------------------------

        uploaded_files = transfer_schedule_gcs_to_google_drive(
            gcs_uri=exported_gcs_uri,
            country_code=country_code,
            year_id=year_id,
            month_id=month_id,
        )
        gcs_to_gdrive_status = SUCCESS_STATUS
        for uploaded_file in uploaded_files:
            LOGGER.info(
                "Scheduled flow uploaded %s to Google Drive: %s",
                uploaded_file["gcs_uri"],
                uploaded_file["drive_url"],
            )

    except Exception as error:
        error_reason = f"{type(error).__name__}: {error}"
        caught_error = error

    # -------------------------------------------------------------------------
    # Build one row for either per-country notification or batch summary.
    # -------------------------------------------------------------------------

    run_record = PipelineRunRecord(
        country_code=country_code,
        year_id=year_id,
        month_id=month_id,
        bq_to_gcs_status=bq_to_gcs_status,
        gcs_to_gdrive_status=gcs_to_gdrive_status,
        error_reason=error_reason,
    )
    return uploaded_files, run_record, caught_error


def _raise_with_original_traceback(error: BaseException) -> None:
    """Raise an error while preserving its original traceback when available."""

    traceback = error.__traceback__
    if isinstance(traceback, TracebackType):
        raise error.with_traceback(traceback)

    raise error


def execute_schedule_export_flow(
    country_code: str,
    sql_path: Path = DEFAULT_SCHEDULE_SQL_PATH,
    run_type: str = "Schedule run (per countrycode)",
    send_notification: bool = True,
) -> list[dict[str, str]]:
    """Run one scheduled export, then optionally send its Lark notification."""

    uploaded_files, run_record, caught_error = _run_schedule_export_steps(
        country_code=country_code,
        sql_path=sql_path,
    )

    # -------------------------------------------------------------------------
    # Notify Lark with the final step-level status for this country run.
    # -------------------------------------------------------------------------

    if send_notification:
        send_lark_pipeline_notification(
            run_type=run_type,
            records=[run_record],
        )

    if caught_error:
        _raise_with_original_traceback(caught_error)

    return uploaded_files


def execute_schedule_export_flow_for_country_file(
    country_codes: list[str],
    sql_path: Path = DEFAULT_SCHEDULE_SQL_PATH,
) -> list[dict[str, str]]:
    """Run scheduled exports for many countries and send one summary card."""

    all_uploaded_files: list[dict[str, str]] = []
    run_records: list[PipelineRunRecord] = []
    failed_country_codes: list[str] = []

    for country_code in country_codes:
        # ---------------------------------------------------------------------
        # Execute each country and collect one summary row for the final card.
        # ---------------------------------------------------------------------

        LOGGER.info("Starting scheduled export flow for COUNTRYCODE=%s", country_code)
        uploaded_files, run_record, caught_error = _run_schedule_export_steps(
            country_code=country_code,
            sql_path=sql_path,
        )
        all_uploaded_files.extend(uploaded_files)
        run_records.append(run_record)

        if caught_error:
            failed_country_codes.append(country_code)
            LOGGER.error(
                "Scheduled export flow failed for COUNTRYCODE=%s.",
                country_code,
                exc_info=(
                    type(caught_error),
                    caught_error,
                    caught_error.__traceback__,
                ),
            )

    # -------------------------------------------------------------------------
    # Send one Lark summary card for the whole country-code file run.
    # -------------------------------------------------------------------------

    send_lark_pipeline_notification(
        run_type="Schedule run (all countrycode file)",
        records=run_records,
    )

    if failed_country_codes:
        failed_country_text = ", ".join(failed_country_codes)
        raise RuntimeError(
            "Scheduled export flow failed for country code(s): "
            f"{failed_country_text}"
        )

    return all_uploaded_files


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
    country_source = parser.add_mutually_exclusive_group(required=True)
    country_source.add_argument(
        "--countrycode",
        "--country-code",
        dest="country_code",
        help="Country code to pass into {COUNTRYCODE}.",
    )
    country_source.add_argument(
        "--country-code-file",
        dest="country_code_file",
        help=(
            "Path to a text file containing country codes. Use one country "
            "code per line, or comma-separated country codes."
        ),
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
    sql_path = Path(arguments.sql_path)

    if arguments.country_code_file:
        country_codes = _read_country_code_file(Path(arguments.country_code_file))
        LOGGER.info(
            "Starting scheduled export flow for %d country code(s).",
            len(country_codes),
        )
        execute_schedule_export_flow_for_country_file(
            country_codes=country_codes,
            sql_path=sql_path,
        )
        return

    execute_schedule_export_flow(
        country_code=arguments.country_code,
        sql_path=sql_path,
    )


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
