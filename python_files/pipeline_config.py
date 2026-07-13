"""Shared pipeline naming configuration helpers."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import os
from string import Formatter
from typing import Any


# =============================================================================
# Default naming templates
# =============================================================================

DEFAULT_PIPELINE_NAME = "STORE_SKU_SALES_MONTH"
DEFAULT_DEPARTMENT = "COA"
DEFAULT_PIPELINE_DISPLAY_NAME_TEMPLATE = "{DEPARTMENT}: {PIPELINE_NAME}"
DEFAULT_GCS_FILE_NAME_TEMPLATE = (
    "{PIPELINE_NAME}_{COUNTRYCODE}_{MM}{YYYY}_{TIMESTAMP}.csv"
)
DEFAULT_DRIVE_FILE_NAME_TEMPLATE = "{PIPELINE_NAME}_{COUNTRYCODE}_{MM}{YYYY}.csv"

GCS_FILE_NAME_TEMPLATE_ENV_NAME = "GCS_FILE_NAME_TEMPLATE"
DRIVE_FILE_NAME_TEMPLATE_ENV_NAME = "DRIVE_FILE_NAME_TEMPLATE"
PIPELINE_NAME_ENV_NAME = "PIPELINE_NAME"
DEPARTMENT_ENV_NAME = "DEPARTMENT"
PIPELINE_DISPLAY_NAME_TEMPLATE_ENV_NAME = "PIPELINE_DISPLAY_NAME_TEMPLATE"

ALLOWED_FILE_NAME_TEMPLATE_FIELDS = {
    "DEPARTMENT",
    "PIPELINE_NAME",
    "COUNTRYCODE",
    "YYYY",
    "MM",
    "YEARID",
    "MONTHID",
    "TIMESTAMP",
}


# =============================================================================
# Environment value helpers
# =============================================================================

def _optional_environment_value(name: str) -> str | None:
    """Return a trimmed environment variable or None when blank."""

    value = os.getenv(name, "").strip()
    return value or None


def pipeline_name() -> str:
    """Return the configured pipeline name used in files and notifications."""

    return _optional_environment_value(PIPELINE_NAME_ENV_NAME) or DEFAULT_PIPELINE_NAME


def department() -> str:
    """Return the configured department name for display labels."""

    return _optional_environment_value(DEPARTMENT_ENV_NAME) or DEFAULT_DEPARTMENT


def pipeline_display_name() -> str:
    """Return the configured pipeline display name for notifications."""

    template = (
        _optional_environment_value(PIPELINE_DISPLAY_NAME_TEMPLATE_ENV_NAME)
        or DEFAULT_PIPELINE_DISPLAY_NAME_TEMPLATE
    )
    return template.format(
        DEPARTMENT=department(),
        PIPELINE_NAME=pipeline_name(),
    ).strip()


# =============================================================================
# File-name template helpers
# =============================================================================

def _validate_file_name_template(template: str, environment_name: str) -> None:
    """Validate that a filename template uses only supported placeholders."""

    field_names = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    unsupported_fields = field_names - ALLOWED_FILE_NAME_TEMPLATE_FIELDS

    if unsupported_fields:
        raise ValueError(
            f"{environment_name} contains unsupported placeholder(s): "
            f"{', '.join(sorted(unsupported_fields))}."
        )


def _validate_file_name(file_name: str, environment_name: str) -> str:
    """Return a safe object filename without folder separators."""

    cleaned_file_name = file_name.strip()
    if not cleaned_file_name:
        raise ValueError(f"{environment_name} produced an empty filename.")

    if "/" in cleaned_file_name or "\\" in cleaned_file_name:
        raise ValueError(
            f"{environment_name} must be a filename only, not a folder path."
        )

    return cleaned_file_name


def _format_file_name_template(
    template: str,
    environment_name: str,
    values: dict[str, Any],
) -> str:
    """Apply a validated filename template to the supplied pipeline values."""

    _validate_file_name_template(
        template=template,
        environment_name=environment_name,
    )
    return _validate_file_name(
        file_name=template.format(**values),
        environment_name=environment_name,
    )


def _file_name_template_values(
    country_code: str,
    year_id: int,
    month_id: int,
    run_timestamp: str | None,
) -> dict[str, Any]:
    """Build reusable values for GCS and Drive filename templates."""

    return {
        "DEPARTMENT": department(),
        "PIPELINE_NAME": pipeline_name(),
        "COUNTRYCODE": country_code,
        "YYYY": f"{year_id:04d}",
        "MM": f"{month_id:02d}",
        "YEARID": year_id,
        "MONTHID": month_id,
        "TIMESTAMP": run_timestamp or "",
    }


def build_gcs_file_name(
    country_code: str,
    year_id: int,
    month_id: int,
    run_timestamp: str,
) -> str:
    """Build the configured timestamped filename used in the GCS bucket."""

    template = (
        _optional_environment_value(GCS_FILE_NAME_TEMPLATE_ENV_NAME)
        or DEFAULT_GCS_FILE_NAME_TEMPLATE
    )
    return _format_file_name_template(
        template=template,
        environment_name=GCS_FILE_NAME_TEMPLATE_ENV_NAME,
        values=_file_name_template_values(
            country_code=country_code,
            year_id=year_id,
            month_id=month_id,
            run_timestamp=run_timestamp,
        ),
    )


def build_drive_file_name(
    country_code: str,
    year_id: int,
    month_id: int,
) -> str:
    """Build the configured final filename used in Google Drive."""

    template = (
        _optional_environment_value(DRIVE_FILE_NAME_TEMPLATE_ENV_NAME)
        or DEFAULT_DRIVE_FILE_NAME_TEMPLATE
    )
    return _format_file_name_template(
        template=template,
        environment_name=DRIVE_FILE_NAME_TEMPLATE_ENV_NAME,
        values=_file_name_template_values(
            country_code=country_code,
            year_id=year_id,
            month_id=month_id,
            run_timestamp=None,
        ),
    )
