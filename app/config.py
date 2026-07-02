"""
Central configuration.

All settings come from environment variables (loaded from a .env file in
development). Nothing is hard-coded — see .env.example for every value.

We use pydantic-settings so values are validated and typed on startup. If a
required variable is missing the app fails fast with a clear error instead of
breaking later in a confusing way.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Telegram ----
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    bot_username: str = Field(..., alias="BOT_USERNAME")
    miniapp_short_name: str = Field("ops", alias="MINIAPP_SHORT_NAME")
    admin_telegram_user_id: int = Field(..., alias="ADMIN_TELEGRAM_USER_ID")
    staff_group_chat_id: int = Field(..., alias="STAFF_GROUP_CHAT_ID")
    telegram_mode: str = Field("webhook", alias="TELEGRAM_MODE")  # webhook|polling

    # ---- Google ----
    google_sheet_id: str = Field(..., alias="GOOGLE_SHEET_ID")
    google_drive_evidence_folder_id: str = Field(
        ..., alias="GOOGLE_DRIVE_EVIDENCE_FOLDER_ID"
    )
    google_service_account_file: str = Field(
        "service_account.json", alias="GOOGLE_SERVICE_ACCOUNT_FILE"
    )
    # On hosts where you cannot upload a file, paste the whole JSON here instead.
    google_service_account_json: Optional[str] = Field(
        None, alias="GOOGLE_SERVICE_ACCOUNT_JSON"
    )
    # MOST ROBUST option for Docker/compose env files: base64 of the JSON.
    # base64 has no backslashes/quotes/newlines, so no parser can mangle the
    # private key's "\n" sequences. Preferred over the raw JSON when set.
    google_service_account_json_b64: Optional[str] = Field(
        None, alias="GOOGLE_SERVICE_ACCOUNT_JSON_B64"
    )

    # ---- Evidence storage ----
    # "local" stores photos on the server's disk (works with a personal Google
    # account). "drive" uploads to Google Drive (needs a Workspace Shared Drive,
    # because plain service accounts have no Drive storage quota).
    storage_backend: str = Field("local", alias="STORAGE_BACKEND")
    storage_dir: str = Field("data/evidence", alias="STORAGE_DIR")

    # ---- App ----
    app_base_url: str = Field(..., alias="APP_BASE_URL")
    secret_key: str = Field(..., alias="SECRET_KEY")
    timezone: str = Field("Asia/Manila", alias="TIMEZONE")
    test_mode: bool = Field(True, alias="TEST_MODE")
    environment_name: str = Field("development", alias="ENVIRONMENT_NAME")
    port: int = Field(8000, alias="PORT")

    # ---- Zite Daily Owner Brief (inventory) — optional integration ----
    # The bot triggers this external report each morning. All optional: if the
    # URL/token are unset the feature is simply inactive (nothing else breaks).
    zite_owner_brief_url: Optional[str] = Field(None, alias="ZITE_OWNER_BRIEF_URL")
    zite_owner_brief_token: Optional[str] = Field(None, alias="ZITE_OWNER_BRIEF_TOKEN")
    owner_emails: str = Field("", alias="OWNER_EMAILS")  # comma-separated recipients
    owner_telegram_chat_id: Optional[int] = Field(None, alias="OWNER_TELEGRAM_CHAT_ID")
    owner_brief_time: str = Field("09:00", alias="OWNER_BRIEF_TIME")  # HH:MM Manila
    # "auto"   -> bot calls the Zite endpoint over HTTP (use once Zite fixes their
    #             external-POST platform bug).
    # "manual" -> bot posts a daily reminder to tap Zite's in-app button instead
    #             (interim while external HTTP is broken). "off" -> do nothing.
    owner_brief_mode: str = Field("auto", alias="OWNER_BRIEF_MODE")

    # ---- Derived helpers ----
    @property
    def base_url(self) -> str:
        return self.app_base_url.rstrip("/")

    @property
    def staff_miniapp_url(self) -> str:
        return f"{self.base_url}/static/staff/index.html"

    @property
    def admin_miniapp_url(self) -> str:
        return f"{self.base_url}/static/admin/index.html"

    @property
    def owner_email_list(self) -> list[str]:
        return [e.strip() for e in (self.owner_emails or "").split(",") if e.strip()]

    @property
    def owner_brief_configured(self) -> bool:
        return bool(self.zite_owner_brief_url and self.zite_owner_brief_token)

    def miniapp_deeplink(self, startapp_token: str) -> str:
        """Direct Mini App deep link used inside the Staff group."""
        return (
            f"https://t.me/{self.bot_username}/{self.miniapp_short_name}"
            f"?startapp={startapp_token}"
        )

    def service_account_info(self) -> dict:
        """Return the parsed service-account credentials dict.

        Order of preference:
          1. base64-encoded JSON (safest through Docker/compose env files)
          2. raw JSON string
          3. JSON file on disk (local development)
        """
        if self.google_service_account_json_b64:
            import base64

            raw = base64.b64decode(self.google_service_account_json_b64)
            return json.loads(raw)
        if self.google_service_account_json:
            return json.loads(self.google_service_account_json)
        path = self.google_service_account_file
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Service account file '{path}' not found and "
                "GOOGLE_SERVICE_ACCOUNT_JSON is not set."
            )
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Import this everywhere."""
    return Settings()  # type: ignore[call-arg]
