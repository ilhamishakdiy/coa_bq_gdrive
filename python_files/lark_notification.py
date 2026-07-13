"""Build and send Lark pipeline notifications."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


# =============================================================================
# Third-party imports
# =============================================================================

from dotenv import load_dotenv


# =============================================================================
# Logging and environment setup
# =============================================================================

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


# =============================================================================
# Project imports
# =============================================================================

from lark_delivery import DEFAULT_LARK_WEBHOOK_ENV_NAME
from lark_delivery import INTERNAL_LARK_WEBHOOK_ENV_NAME
from lark_delivery import USER_LARK_WEBHOOK_ENV_NAME
from lark_delivery import send_lark_payload_to_any
from pipeline_config import pipeline_display_name
from pipeline_config import pipeline_name


# =============================================================================
# Constants
# =============================================================================

PIPELINE_NAME = pipeline_name()
LARK_WEBHOOK_ENV_NAME = DEFAULT_LARK_WEBHOOK_ENV_NAME
PIPELINE_LARK_WEBHOOK_ENV_NAMES = (
    INTERNAL_LARK_WEBHOOK_ENV_NAME,
    USER_LARK_WEBHOOK_ENV_NAME,
    DEFAULT_LARK_WEBHOOK_ENV_NAME,
)
DRIVE_FOLDER_ENV_NAME = "DRIVE_FOLDER_ID"
LARK_TABLE_PAGE_SIZE_ENV_NAME = "LARK_TABLE_PAGE_SIZE"
SUCCESS_STATUS = "success"
FAILED_STATUS = "failed"
EMPTY_ERROR_REASON = "-"


# =============================================================================
# Notification data model
# =============================================================================

@dataclass(frozen=True)
class PipelineRunRecord:
    """Represent one country/month pipeline result row."""

    country_code: str
    year_id: int
    month_id: int
    bq_to_gcs_status: str
    gcs_to_gdrive_status: str
    error_reason: str = EMPTY_ERROR_REASON


# =============================================================================
# Formatting helpers
# =============================================================================

def _pipeline_succeeded(records: list[PipelineRunRecord]) -> bool:
    """Return whether every pipeline step in every record succeeded."""

    if not records:
        return False

    return all(
        record.bq_to_gcs_status == SUCCESS_STATUS
        and record.gcs_to_gdrive_status == SUCCESS_STATUS
        for record in records
    )


def _status_text(is_success: bool) -> str:
    """Return the title-case pipeline status text."""

    return "Succeeded" if is_success else "Failed"


def _escape_markdown_table_cell(value: Any) -> str:
    """Return a safe single-line text value for a Lark table cell."""

    text = str(value).replace("\r\n", " ").replace("\n", " ").strip()
    return text or EMPTY_ERROR_REASON


def _build_table_columns() -> list[dict[str, str]]:
    """Build the native Lark table column definitions."""

    return [
        {
            "name": "country_code",
            "display_name": "COUNTRYCODE",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "120px",
        },
        {
            "name": "year_id",
            "display_name": "YEARID",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "100px",
        },
        {
            "name": "month_id",
            "display_name": "MONTHID",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "100px",
        },
        {
            "name": "bq_to_gcs_status",
            "display_name": "BQ to GCS",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "120px",
        },
        {
            "name": "gcs_to_gdrive_status",
            "display_name": "GCS to Gdrive",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "140px",
        },
        {
            "name": "error_reason",
            "display_name": "Error reason",
            "data_type": "text",
            "horizontal_align": "left",
            "width": "240px",
        },
    ]


def _build_table_rows(records: list[PipelineRunRecord]) -> list[dict[str, str]]:
    """Build the native Lark table row values."""

    return [
        {
            "country_code": _escape_markdown_table_cell(record.country_code),
            "year_id": _escape_markdown_table_cell(record.year_id),
            "month_id": _escape_markdown_table_cell(record.month_id),
            "bq_to_gcs_status": _escape_markdown_table_cell(
                record.bq_to_gcs_status
            ),
            "gcs_to_gdrive_status": _escape_markdown_table_cell(
                record.gcs_to_gdrive_status
            ),
            "error_reason": _escape_markdown_table_cell(record.error_reason),
        }
        for record in records
    ]


def _lark_table_page_size(record_count: int) -> int:
    """Return the configured Lark table page size for summary rows."""

    configured_page_size = os.getenv(LARK_TABLE_PAGE_SIZE_ENV_NAME, "").strip()
    if not configured_page_size:
        return max(1, record_count)

    try:
        page_size = int(configured_page_size)
    except ValueError as error:
        raise ValueError(
            f"{LARK_TABLE_PAGE_SIZE_ENV_NAME} must be a whole number."
        ) from error

    if page_size <= 0:
        raise ValueError(f"{LARK_TABLE_PAGE_SIZE_ENV_NAME} must be positive.")

    return page_size


def _build_lark_table(records: list[PipelineRunRecord]) -> dict[str, Any]:
    """Build a native Lark table element for load details."""

    return {
        "tag": "table",
        "page_size": _lark_table_page_size(len(records)),
        "row_height": "low",
        "freeze_first_column": True,
        "header_style": {
            "text_align": "left",
            "text_size": "normal",
            "background_style": "grey",
            "text_color": "default",
            "bold": True,
            "lines": 1,
        },
        "columns": _build_table_columns(),
        "rows": _build_table_rows(records),
    }


def _formatted_now() -> tuple[str, str]:
    """Return current local date and time strings for the card summary."""

    current_datetime = datetime.now(timezone.utc).astimezone()
    return (
        current_datetime.strftime("%Y-%m-%d"),
        current_datetime.strftime("%H:%M:%S %z"),
    )


def _drive_folder_url() -> str | None:
    """Return the configured Google Drive folder URL for the card summary."""

    drive_folder_id = os.getenv(DRIVE_FOLDER_ENV_NAME, "").strip()
    if not drive_folder_id:
        return None

    return (
        "https://drive.google.com/drive/folders/"
        f"{quote(drive_folder_id, safe='')}"
    )


# =============================================================================
# Lark card builder
# =============================================================================

def build_lark_pipeline_card(
    run_type: str,
    records: list[PipelineRunRecord],
) -> dict[str, Any]:
    """Build a Lark interactive card payload for a pipeline run."""

    is_success = _pipeline_succeeded(records)
    status_text = _status_text(is_success)
    card_date, card_time = _formatted_now()
    configured_pipeline_display_name = pipeline_display_name()
    drive_folder_url = _drive_folder_url()

    summary_lines = [
        f"**Date:** {card_date}",
        f"**Time:** {card_time}",
    ]
    if drive_folder_url:
        summary_lines.append(f"**Google Drive folder:** {drive_folder_url}")

    summary_lines.extend(
        [
            f"**Run type:** {run_type}",
            f"**Pipeline:** {SUCCESS_STATUS if is_success else FAILED_STATUS}",
        ]
    )
    summary_markdown = "\n".join(summary_lines)

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
                "width_mode": "fill",
            },
            "header": {
                "template": "green" if is_success else "red",
                "title": {
                    "tag": "plain_text",
                    "content": (
                        f"{configured_pipeline_display_name} Pipeline "
                        f"{status_text}"
                    ),
                },
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": summary_markdown,
                    },
                    {
                        "tag": "hr",
                    },
                    {
                        "tag": "markdown",
                        "content": "Load Details",
                    },
                    _build_lark_table(records),
                ],
            },
        },
    }


def send_lark_pipeline_notification(
    run_type: str,
    records: list[PipelineRunRecord],
) -> None:
    """Send a Lark pipeline notification when a webhook URL is configured."""

    payload = build_lark_pipeline_card(
        run_type=run_type,
        records=records,
    )
    send_lark_payload_to_any(
        payload=payload,
        webhook_env_names=PIPELINE_LARK_WEBHOOK_ENV_NAMES,
        notification_name=f"Lark pipeline notification for {run_type}",
    )
