"""Tests for pipeline execution notifications."""

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
from manual_run_script import manual_execute_export_flow
from schedule_run_script import schedule_execute_export_flow


# =============================================================================
# Manual flow notification tests
# =============================================================================

class ManualFlowNotificationTests(unittest.TestCase):
    """Validate manual run notification statuses."""

    @mock.patch.object(manual_execute_export_flow, "send_lark_pipeline_notification")
    @mock.patch.object(manual_execute_export_flow, "transfer_manual_gcs_to_google_drive")
    @mock.patch.object(manual_execute_export_flow, "export_manual_bigquery_to_gcs")
    def test_manual_success_notifies_success_statuses(
        self,
        mock_export: mock.Mock,
        mock_transfer: mock.Mock,
        mock_notify: mock.Mock,
    ) -> None:
        """Send a success notification after both manual steps finish."""

        mock_export.return_value = "gs://bucket/file.csv"
        mock_transfer.return_value = [
            {
                "gcs_uri": "gs://bucket/file.csv",
                "drive_url": "https://drive.example/file",
            }
        ]

        manual_execute_export_flow.execute_manual_export_flow(
            country_code="BD",
            year_id=2026,
            month_id=6,
        )

        record = mock_notify.call_args.kwargs["records"][0]
        self.assertEqual(mock_notify.call_args.kwargs["run_type"], "Manual run")
        self.assertEqual(record.country_code, "BD")
        self.assertEqual(record.year_id, 2026)
        self.assertEqual(record.month_id, 6)
        self.assertEqual(record.bq_to_gcs_status, SUCCESS_STATUS)
        self.assertEqual(record.gcs_to_gdrive_status, SUCCESS_STATUS)

    @mock.patch.object(manual_execute_export_flow, "send_lark_pipeline_notification")
    @mock.patch.object(manual_execute_export_flow, "export_manual_bigquery_to_gcs")
    def test_manual_export_failure_notifies_failed_statuses(
        self,
        mock_export: mock.Mock,
        mock_notify: mock.Mock,
    ) -> None:
        """Send a failed notification when manual BigQuery export fails."""

        mock_export.side_effect = RuntimeError("export failed")

        with self.assertRaises(RuntimeError):
            manual_execute_export_flow.execute_manual_export_flow(
                country_code="BD",
                year_id=2026,
                month_id=6,
            )

        record = mock_notify.call_args.kwargs["records"][0]
        self.assertEqual(record.bq_to_gcs_status, FAILED_STATUS)
        self.assertEqual(record.gcs_to_gdrive_status, FAILED_STATUS)
        self.assertIn("export failed", record.error_reason)


# =============================================================================
# Schedule flow notification tests
# =============================================================================

class ScheduleFlowNotificationTests(unittest.TestCase):
    """Validate scheduled run notification statuses."""

    @mock.patch.object(schedule_execute_export_flow, "send_lark_pipeline_notification")
    @mock.patch.object(schedule_execute_export_flow, "transfer_schedule_gcs_to_google_drive")
    @mock.patch.object(schedule_execute_export_flow, "export_schedule_bigquery_to_gcs")
    @mock.patch.object(schedule_execute_export_flow, "_previous_month_period")
    def test_schedule_success_notifies_config_file_run_type(
        self,
        mock_previous_month_period: mock.Mock,
        mock_export: mock.Mock,
        mock_transfer: mock.Mock,
        mock_notify: mock.Mock,
    ) -> None:
        """Send success status for scheduled config-file country runs."""

        mock_previous_month_period.return_value = (2026, 6)
        mock_export.return_value = "gs://bucket/file.csv"
        mock_transfer.return_value = [
            {
                "gcs_uri": "gs://bucket/file.csv",
                "drive_url": "https://drive.example/file",
            }
        ]

        schedule_execute_export_flow.execute_schedule_export_flow(
            country_code="IN",
            run_type="Schedule run (all countrycode file)",
        )

        record = mock_notify.call_args.kwargs["records"][0]
        self.assertEqual(
            mock_notify.call_args.kwargs["run_type"],
            "Schedule run (all countrycode file)",
        )
        self.assertEqual(record.country_code, "IN")
        self.assertEqual(record.year_id, 2026)
        self.assertEqual(record.month_id, 6)
        self.assertEqual(record.bq_to_gcs_status, SUCCESS_STATUS)
        self.assertEqual(record.gcs_to_gdrive_status, SUCCESS_STATUS)

    @mock.patch.object(schedule_execute_export_flow, "send_lark_pipeline_notification")
    @mock.patch.object(schedule_execute_export_flow, "transfer_schedule_gcs_to_google_drive")
    @mock.patch.object(schedule_execute_export_flow, "export_schedule_bigquery_to_gcs")
    @mock.patch.object(schedule_execute_export_flow, "_previous_month_period")
    def test_schedule_drive_failure_keeps_bq_success(
        self,
        mock_previous_month_period: mock.Mock,
        mock_export: mock.Mock,
        mock_transfer: mock.Mock,
        mock_notify: mock.Mock,
    ) -> None:
        """Report BigQuery success and Drive failure when upload fails."""

        mock_previous_month_period.return_value = (2026, 6)
        mock_export.return_value = "gs://bucket/file.csv"
        mock_transfer.side_effect = RuntimeError("drive failed")

        with self.assertRaises(RuntimeError):
            schedule_execute_export_flow.execute_schedule_export_flow(
                country_code="IN",
            )

        record = mock_notify.call_args.kwargs["records"][0]
        self.assertEqual(record.bq_to_gcs_status, SUCCESS_STATUS)
        self.assertEqual(record.gcs_to_gdrive_status, FAILED_STATUS)
        self.assertIn("drive failed", record.error_reason)


# =============================================================================
# Test entry point
# =============================================================================

if __name__ == "__main__":
    unittest.main()
