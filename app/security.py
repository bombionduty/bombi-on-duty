"""
Security helpers: Telegram WebApp initData validation + task token handling.

Telegram authentication (spec section 7)
----------------------------------------
A Mini App sends `Telegram.WebApp.initData` (a query string). We MUST validate
its `hash` on the server using our bot token before trusting ANY field. We never
trust user IDs / names supplied directly by the browser.

Algorithm (official Telegram spec):
  secret_key = HMAC_SHA256(key="WebAppData", data=bot_token)
  check = HMAC_SHA256(key=secret_key, data=data_check_string)
  valid if check == hash

Task tokens (spec section 6 + 45)
---------------------------------
Each task gets a random, hard-to-guess token used in the Mini App deep link. We
store only its SHA-256 hash in the sheet, never the raw token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl

from app.config import get_settings


# --------------------------------------------------------------------------
# Task tokens
# --------------------------------------------------------------------------
def new_task_token() -> str:
    """A URL-safe random token tied to one task."""
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    """SHA-256 hex digest stored in the sheet (raw token is never stored)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Telegram initData validation
# --------------------------------------------------------------------------
class InitDataError(Exception):
    """Raised when initData fails validation."""


def validate_init_data(init_data: str, max_age_seconds: int = 24 * 3600) -> dict:
    """Validate raw initData and return the parsed, trusted fields.

    Returns a dict like {"user": {...}, "auth_date": 123, "start_param": "..."}.
    Raises InitDataError on any failure.
    """
    if not init_data:
        raise InitDataError("Missing initData")

    settings = get_settings()
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("initData has no hash")

    # Build the data-check-string: keys sorted, "key=value" joined by newline.
    data_check_string = "\n".join(
        f"{k}={pairs[k]}" for k in sorted(pairs.keys())
    )

    secret_key = hmac.new(
        b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
    ).digest()
    calc_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        raise InitDataError("initData hash mismatch")

    # Reject stale initData.
    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date and (time.time() - auth_date) > max_age_seconds:
        raise InitDataError("initData expired")

    result: dict = dict(pairs)
    if "user" in pairs:
        try:
            result["user"] = json.loads(pairs["user"])
        except json.JSONDecodeError:
            raise InitDataError("Bad user field in initData")
    return result


def extract_user_id(validated: dict) -> int:
    user = validated.get("user")
    if not user or "id" not in user:
        raise InitDataError("No user id in initData")
    return int(user["id"])
