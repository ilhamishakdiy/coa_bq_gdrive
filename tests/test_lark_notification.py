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
from lark_notification import SUCCESS_STATUS
from lark_notification import PipelineRunRecord
from lark_notification import build_lark_pipeline_card
from lark_notification import send_lark_pipeline_notification
from lark_delivery import send_lark_payload
from lark_delivery import send_lark_payload_to_any
from pipeline_config import pipeline_display_name


# =============================================================================
# Card builder tests
# =============================================================================

class LarkPipelineCardTests(unittest.TestCase):
    """Validate Lark card payload formatting."""

    @mock.patch.dict("os.environ", {}, clear=True)
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
        self.assertEqual(table["page_size"], 1)
        self.assertEqual(
            card["header"]["title"]["content"],
            f"{pipeline_display_name()} Pipeline Succeeded",
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

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_table_page_size_defaults_to_all_records(self) -> None:
        """Show all summary rows on one table page by default."""

        payload = build_lark_pipeline_card(
            run_type="Schedule run",
            records=[
                PipelineRunRecord(
                    country_code=country_code,
                    year_id=2026,
                    month_id=6,
                    bq_to_gcs_status=SUCCESS_STATUS,
                    gcs_to_gdrive_status=SUCCESS_STATUS,
                )
                for country_code in ("BD", "MY", "SG")
            ],
        )

        table = payload["card"]["body"]["elements"][3]

        self.assertEqual(table["page_size"], 3)

    @mock.patch.dict("os.environ", {"LARK_TABLE_PAGE_SIZE": "2"}, clear=True)
    def test_table_page_size_can_be_configured(self) -> None:
        """Use the configured Lark table page size when provided."""

        payload = build_lark_pipeline_card(
            run_type="Schedule run",
            records=[
                PipelineRunRecord(
                    country_code=country_code,
                    year_id=2026,
                    month_id=6,
                    bq_to_gcs_status=SUCCESS_STATUS,
                    gcs_to_gdrive_status=SUCCESS_STATUS,
                )
                for country_code in ("BD", "MY", "SG")
            ],
        )

        table = payload["card"]["body"]["elements"][3]

        self.assertEqual(table["page_size"], 2)

    @mock.patch.dict("os.environ", {"DRIVE_FOLDER_ID": "folder id"}, clear=True)
    def test_card_summary_contains_drive_folder_url_after_time(self) -> None:
        """Show the configured Google Drive folder URL after the card time."""

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

        summary_lines = payload["card"]["body"]["elements"][0]["content"].splitlines()

        self.assertTrue(summary_lines[1].startswith("**Time:** "))
        self.assertEqual(
            summary_lines[2],
            "**Google Drive folder:** "
            "https://drive.google.com/drive/folders/folder%20id",
        )
        self.assertEqual(summary_lines[3], "**Run type:** Manual run")

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
            f"{pipeline_display_name()} Pipeline Failed",
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

    @mock.patch("lark_notification.send_lark_payload_to_any")
    def test_pipeline_notification_delegates_to_multi_webhook_sender(
        self,
        mock_send_lark_payload_to_any: mock.Mock,
    ) -> None:
        """Build the pipeline card and send it to the reusable multi-sender."""

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

        mock_send_lark_payload_to_any.assert_called_once()
        sent_payload = mock_send_lark_payload_to_any.call_args.kwargs["payload"]
        env_names = mock_send_lark_payload_to_any.call_args.kwargs[
            "webhook_env_names"
        ]
        self.assertEqual(sent_payload["msg_type"], "interactive")
        self.assertIn("INTERNAL_LARK_WEBHOOK_URL", env_names)
        self.assertIn("USER_LARK_WEBHOOK_URL", env_names)
        self.assertIn("LARK_WEBHOOK_URL", env_names)
        self.assertIn(
            "Manual run",
            sent_payload["card"]["body"]["elements"][0]["content"],
        )

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("lark_delivery.post_lark_webhook")
    def test_generic_sender_skips_when_webhook_is_missing(
        self,
        mock_post_lark_webhook: mock.Mock,
    ) -> None:
        """Do not call Lark when the webhook environment value is missing."""

        was_sent = send_lark_payload(
            payload={"msg_type": "text", "content": {"text": "hello"}},
        )

        self.assertFalse(was_sent)
        mock_post_lark_webhook.assert_not_called()

    @mock.patch.dict(
        "os.environ",
        {
            "INTERNAL_LARK_WEBHOOK_URL": "https://internal.example/webhook",
            "USER_LARK_WEBHOOK_URL": "https://user.example/webhook",
        },
        clear=True,
    )
    @mock.patch("lark_delivery.post_lark_webhook")
    def test_multi_sender_posts_to_internal_and_user_webhooks(
        self,
        mock_post_lark_webhook: mock.Mock,
    ) -> None:
        """Send one payload to every configured webhook env value."""

        payload = {"msg_type": "text", "content": {"text": "hello"}}

        sent_count = send_lark_payload_to_any(
            payload=payload,
            webhook_env_names=(
                "INTERNAL_LARK_WEBHOOK_URL",
                "USER_LARK_WEBHOOK_URL",
            ),
        )

        self.assertEqual(sent_count, 2)
        self.assertEqual(mock_post_lark_webhook.call_count, 2)
        self.assertEqual(
            [
                call.kwargs["webhook_url"]
                for call in mock_post_lark_webhook.call_args_list
            ],
            [
                "https://internal.example/webhook",
                "https://user.example/webhook",
            ],
        )

    @mock.patch.dict(
        "os.environ",
        {
            "INTERNAL_LARK_WEBHOOK_URL": "https://same.example/webhook",
            "USER_LARK_WEBHOOK_URL": "https://same.example/webhook",
        },
        clear=True,
    )
    @mock.patch("lark_delivery.post_lark_webhook")
    def test_multi_sender_skips_duplicate_webhook_urls(
        self,
        mock_post_lark_webhook: mock.Mock,
    ) -> None:
        """Avoid sending duplicate cards when two env names share one URL."""

        sent_count = send_lark_payload_to_any(
            payload={"msg_type": "text", "content": {"text": "hello"}},
            webhook_env_names=(
                "INTERNAL_LARK_WEBHOOK_URL",
                "USER_LARK_WEBHOOK_URL",
            ),
        )

        self.assertEqual(sent_count, 1)
        mock_post_lark_webhook.assert_called_once()


# =============================================================================
# Test entry point
# =============================================================================

if __name__ == "__main__":
    unittest.main()
