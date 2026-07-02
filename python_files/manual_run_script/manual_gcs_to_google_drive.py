"""Transfer a manual GCS extract file to Google Drive."""

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

from gcs_to_google_drive import transfer_gcs_to_google_drive  # noqa: E402


# =============================================================================
# Logging configuration
# =============================================================================

LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# =============================================================================
# Public transfer function
# =============================================================================

def transfer_manual_gcs_to_google_drive(
    gcs_uri: str | None = None,
) -> list[dict[str, str]]:
    """Transfer a manual GCS export URI to Google Drive."""

    # -------------------------------------------------------------------------
    # Reuse the shared transfer flow so Drive upload behavior stays consistent.
    # -------------------------------------------------------------------------

    return transfer_gcs_to_google_drive(gcs_uri)


# =============================================================================
# Command line interface
# =============================================================================

def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the optional manual GCS URI from the command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Upload a manual GCS extract file to the configured Google Drive "
            "folder."
        )
    )
    parser.add_argument(
        "--gcs-uri",
        default=None,
        help=(
            "Exact or wildcard GCS URI to upload. When omitted, the shared "
            "GCS_DRIVE_SOURCE_URI/latest merged-object fallback is used."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the manual GCS-to-Google-Drive transfer."""

    arguments = _parse_arguments(argv)
    uploaded_files = transfer_manual_gcs_to_google_drive(arguments.gcs_uri)

    # -------------------------------------------------------------------------
    # Log each uploaded Drive file for easy manual-run tracking.
    # -------------------------------------------------------------------------

    for uploaded_file in uploaded_files:
        LOGGER.info(
            "Uploaded %s to Google Drive: %s",
            uploaded_file["gcs_uri"],
            uploaded_file["drive_url"],
        )


# =============================================================================
# Standalone entry point
# =============================================================================

if __name__ == "__main__":
    main()
