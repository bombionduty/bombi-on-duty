"""Token + initData validation tests (spec sections 7, 45)."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.config import get_settings
from app.security import (
    InitDataError,
    hash_token,
    new_task_token,
    validate_init_data,
)


def _make_init_data(user_id: int) -> str:
    """Build a valid initData string the way Telegram would."""
    token = get_settings().telegram_bot_token
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAA",
        "user": json.dumps({"id": user_id, "first_name": "Tess"}),
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_token_hash_is_deterministic_and_token_unique():
    t = new_task_token()
    assert hash_token(t) == hash_token(t)
    assert new_task_token() != new_task_token()
    assert len(hash_token(t)) == 64


def test_valid_init_data_round_trip():
    validated = validate_init_data(_make_init_data(42))
    assert validated["user"]["id"] == 42


def test_tampered_init_data_rejected():
    raw = _make_init_data(42).replace("Tess", "Eve")
    with pytest.raises(InitDataError):
        validate_init_data(raw)


def test_missing_hash_rejected():
    with pytest.raises(InitDataError):
        validate_init_data("user=%7B%7D&auth_date=1")
