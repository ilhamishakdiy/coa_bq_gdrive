"""Build and send Lark pipeline notifications."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib import error
from urllib import request


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
# Constants
# =============================================================================

PIPELINE_NAME = "coa_bq_to_gdrive"
LARK_WEBHOOK_ENV_NAME = "LARK_WEBHOOK_URL"
LARK_REQUEST_TIMEOUT_SECONDS = 15
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


def _build_lark_table(records: list[PipelineRunRecord]) -> dict[str, Any]:
    """Build a native Lark table element for load details."""

    return {
        "tag": "table",
        "page_size": max(1, min(len(records), 10)),
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

    summary_markdown = (
        f"**Date:** {card_date}\n"
        f"**Time:** {card_time}\n"
        f"**Run type:** {run_type}\n"
        f"**Pipeline:** {SUCCESS_STATUS if is_success else FAILED_STATUS}"
    )

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
                    "content": f"{PIPELINE_NAME} Pipeline {status_text}",
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


# =============================================================================
# Webhook delivery
# =============================================================================

def _post_lark_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    """Post one JSON payload to the configured Lark webhook URL."""

    request_body = json.dumps(payload).encode("utf-8")
    webhook_request = request.Request(
        webhook_url,
        data=request_body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    with request.urlopen(
        webhook_request,
        timeout=LARK_REQUEST_TIMEOUT_SECONDS,
    ) as response:
        response_body = response.read().decode("utf-8")

    if not response_body:
        return

    try:
        response_json = json.loads(response_body)
    except json.JSONDecodeError:
        LOGGER.debug("Lark webhook returned a non-JSON response: %s", response_body)
        return

    if response_json.get("code", 0) not in {0, "0"}:
        raise RuntimeError(f"Lark webhook returned an error response: {response_body}")


def send_lark_pipeline_notification(
    run_type: str,
    records: list[PipelineRunRecord],
) -> None:
    """Send a Lark pipeline notification when a webhook URL is configured."""

    webhook_url = os.getenv(LARK_WEBHOOK_ENV_NAME, "").strip()
    if not webhook_url:
        LOGGER.info("%s is not set. Skipping Lark notification.", LARK_WEBHOOK_ENV_NAME)
        return

    payload = build_lark_pipeline_card(
        run_type=run_type,
        records=records,
    )

    try:
        _post_lark_webhook(
            webhook_url=webhook_url,
            payload=payload,
        )
        LOGGER.info("Lark pipeline notification sent for %s.", run_type)
    except (OSError, RuntimeError, error.URLError, error.HTTPError):
        LOGGER.exception("Failed to send Lark pipeline notification.")
