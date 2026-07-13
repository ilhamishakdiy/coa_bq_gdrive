"""Tests for shared pipeline naming configuration."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import os
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

from pipeline_config import build_drive_file_name
from pipeline_config import build_gcs_file_name
from pipeline_config import department
from pipeline_config import pipeline_display_name
from pipeline_config import pipeline_name


# =============================================================================
# Pipeline naming tests
# =============================================================================

class PipelineConfigTests(unittest.TestCase):
    """Validate environment-driven pipeline and filename configuration."""

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_default_file_names_match_existing_convention(self) -> None:
        """Use the legacy filename shape when templates are not configured."""

        self.assertEqual(department(), "COA")
        self.assertEqual(pipeline_name(), "STORE_SKU_SALES_MONTH")
        self.assertEqual(
            pipeline_display_name(),
            "COA: STORE_SKU_SALES_MONTH",
        )
        self.assertEqual(
            build_gcs_file_name(
                country_code="BD",
                year_id=2026,
                month_id=6,
                run_timestamp="20260703T120000Z",
            ),
            "STORE_SKU_SALES_MONTH_BD_062026_20260703T120000Z.csv",
        )
        self.assertEqual(
            build_drive_file_name(
                country_code="BD",
                year_id=2026,
                month_id=6,
            ),
            "STORE_SKU_SALES_MONTH_BD_062026.csv",
        )

    @mock.patch.dict(
        os.environ,
        {
            "DEPARTMENT": "FIN",
            "PIPELINE_NAME": "CUSTOM_PIPELINE",
            "PIPELINE_DISPLAY_NAME_TEMPLATE": (
                "{DEPARTMENT}: {PIPELINE_NAME}"
            ),
            "GCS_FILE_NAME_TEMPLATE": (
                "{DEPARTMENT}-{PIPELINE_NAME}-{COUNTRYCODE}-{YYYY}-{MM}-"
                "{TIMESTAMP}.csv"
            ),
            "DRIVE_FILE_NAME_TEMPLATE": (
                "{DEPARTMENT}-{PIPELINE_NAME}-{COUNTRYCODE}-{YYYY}-{MM}.csv"
            ),
        },
        clear=True,
    )
    def test_custom_file_name_templates_use_environment_values(self) -> None:
        """Use configured filename templates for reusable pipelines."""

        self.assertEqual(department(), "FIN")
        self.assertEqual(pipeline_name(), "CUSTOM_PIPELINE")
        self.assertEqual(pipeline_display_name(), "FIN: CUSTOM_PIPELINE")
        self.assertEqual(
            build_gcs_file_name(
                country_code="MY",
                year_id=2026,
                month_id=7,
                run_timestamp="20260801T010203Z",
            ),
            "FIN-CUSTOM_PIPELINE-MY-2026-07-20260801T010203Z.csv",
        )
        self.assertEqual(
            build_drive_file_name(
                country_code="MY",
                year_id=2026,
                month_id=7,
            ),
            "FIN-CUSTOM_PIPELINE-MY-2026-07.csv",
        )

    @mock.patch.dict(
        os.environ,
        {
            "GCS_FILE_NAME_TEMPLATE": "{UNKNOWN_PLACEHOLDER}.csv",
        },
        clear=True,
    )
    def test_unknown_template_placeholder_fails_loudly(self) -> None:
        """Reject unsupported placeholders before building a bad filename."""

        with self.assertRaisesRegex(ValueError, "UNKNOWN_PLACEHOLDER"):
            build_gcs_file_name(
                country_code="BD",
                year_id=2026,
                month_id=6,
                run_timestamp="20260703T120000Z",
            )


# =============================================================================
# Test entry point
# =============================================================================

if __name__ == "__main__":
    unittest.main()
