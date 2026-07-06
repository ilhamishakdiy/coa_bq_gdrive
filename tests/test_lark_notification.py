"""Tests for Lark pipeline notification payloads."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


# =============================================================================
# Project import path setup
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES_FOLDER = PROJECT_ROOT / "python_files"

if str(PYTHON_FILES_FOLDER) not in sys.path:
    sys.path.insert(0, str(PYTHON_FILES_FOLDER))


# =============================================================================
# Project imports
# =============================================================================

from lark_notification import FAILED_STATUS
from lark_notification import PIPELINE_NAME
from lark_notification import SUCCESS_STATUS
from lark_notification import PipelineRunRecord
from lark_notification import build_lark_pipeline_card
from lark_notification import send_lark_pipeline_notification


# =============================================================================
# Card builder tests
# =============================================================================

class LarkPipelineCardTests(unittest.TestCase):
    """Validate Lark card payload formatting."""

    def test_success_card_contains_expected_summary_and_table(self) -> None:
        """Build a green success card with the requested run details."""

        payload = build_lark_pipeline_card(
            run_type="Manual run",
            records=[
                PipelineRunRecord(
                    country_code="BD",
                    year_id=2026,
                    month_id=6,
                    bq_to_gcs_status=SUCCESS_STATUS,
                    gcs_to_gdrive_status=SUCCESS_STATUS,
                )
            ],
        )

        card = payload["card"]
        body_elements = card["body"]["elements"]
        summary = body_elements[0]["content"]
        table = body_elements[3]

        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["config"]["width_mode"], "fill")
        self.assertEqual(card["header"]["template"], "green")
        self.assertEqual(
            card["header"]["title"]["content"],
            f"{PIPELINE_NAME} Pipeline Succeeded",
        )
        self.assertIn("**Run type:** Manual run", summary)
        self.assertEqual(table["tag"], "table")
        self.assertEqual(table["columns"][0]["display_name"], "COUNTRYCODE")
        self.assertEqual(
            table["rows"][0],
            {
                "country_code": "BD",
                "year_id": "2026",
                "month_id": "6",
                "bq_to_gcs_status": "success",
                "gcs_to_gdrive_status": "success",
                "error_reason": "-",
            },
        )

    def test_failed_card_contains_error_reason(self) -> None:
        """Build a red failed card with an escaped error reason."""

        payload = build_lark_pipeline_card(
            run_type="Schedule run",
            records=[
                PipelineRunRecord(
                    country_code="IN",
                    year_id=2026,
                    month_id=6,
                    bq_to_gcs_status=SUCCESS_STATUS,
                    gcs_to_gdrive_status=FAILED_STATUS,
                    error_reason="Upload failed | retry later\ncheck logs",
                )
            ],
        )

        card = payload["card"]
        table = card["body"]["elements"][3]

        self.assertEqual(card["header"]["template"], "red")
        self.assertEqual(
            card["header"]["title"]["content"],
            f"{PIPELINE_NAME} Pipeline Failed",
        )
        self.assertEqual(
            table["rows"][0]["error_reason"],
            "Upload failed | retry later check logs",
        )


# =============================================================================
# Delivery tests
# =============================================================================

class LarkPipelineDeliveryTests(unittest.TestCase):
    """Validate notification delivery guardrails."""

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("lark_notification._post_lark_webhook")
    def test_notification_skips_when_webhook_is_missing(
        self,
        mock_post_lark_webhook: mock.Mock,
    ) -> None:
        """Do not call Lark when LARK_WEBHOOK_URL is missing."""

        send_lark_pipeline_notification(
            run_type="Manual run",
            records=[
                PipelineRunRecord(
                    country_code="BD",
                    year_id=2026,
                    month_id=6,
                    bq_to_gcs_status=SUCCESS_STATUS,
                    gcs_to_gdrive_status=SUCCESS_STATUS,
                )
            ],
        )

        mock_post_lark_webhook.assert_not_called()


# =============================================================================
# Test entry point
# =============================================================================

if __name__ == "__main__":
    unittest.main()
