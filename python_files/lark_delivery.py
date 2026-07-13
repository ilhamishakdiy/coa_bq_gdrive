"""Send reusable Lark webhook payloads."""

# =============================================================================
# Standard library imports
# =============================================================================

from __future__ import annotations

import json
import logging
import os
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

DEFAULT_LARK_WEBHOOK_ENV_NAME = "LARK_WEBHOOK_URL"
INTERNAL_LARK_WEBHOOK_ENV_NAME = "INTERNAL_LARK_WEBHOOK_URL"
USER_LARK_WEBHOOK_ENV_NAME = "USER_LARK_WEBHOOK_URL"
LARK_REQUEST_TIMEOUT_SECONDS = 15


# =============================================================================
# Webhook delivery
# =============================================================================

def post_lark_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
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


def send_lark_payload(
    payload: dict[str, Any],
    webhook_env_name: str = DEFAULT_LARK_WEBHOOK_ENV_NAME,
    notification_name: str = "Lark notification",
) -> bool:
    """Send a prepared Lark payload when a webhook URL is configured."""

    webhook_url = os.getenv(webhook_env_name, "").strip()
    if not webhook_url:
        LOGGER.info("%s is not set. Skipping %s.", webhook_env_name, notification_name)
        return False

    try:
        post_lark_webhook(
            webhook_url=webhook_url,
            payload=payload,
        )
        LOGGER.info("%s sent.", notification_name)
        return True
    except (OSError, RuntimeError, error.URLError, error.HTTPError):
        LOGGER.exception("Failed to send %s.", notification_name)
        return False


def send_lark_payload_to_any(
    payload: dict[str, Any],
    webhook_env_names: tuple[str, ...],
    notification_name: str = "Lark notification",
) -> int:
    """Send a prepared Lark payload to each configured webhook env value."""

    sent_count = 0
    seen_webhook_urls: set[str] = set()

    for webhook_env_name in webhook_env_names:
        webhook_url = os.getenv(webhook_env_name, "").strip()
        if not webhook_url:
            LOGGER.info(
                "%s is not set. Skipping %s.",
                webhook_env_name,
                notification_name,
            )
            continue

        if webhook_url in seen_webhook_urls:
            LOGGER.info(
                "%s duplicates an earlier webhook. Skipping %s.",
                webhook_env_name,
                notification_name,
            )
            continue

        if send_lark_payload(
            payload=payload,
            webhook_env_name=webhook_env_name,
            notification_name=f"{notification_name} via {webhook_env_name}",
        ):
            sent_count += 1
            seen_webhook_urls.add(webhook_url)

    return sent_count
