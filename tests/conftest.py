"""
Test fixtures. We set the minimum environment so app.config loads without a real
.env, and we never touch Google or Telegram here — only pure logic is tested.
"""
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST-TOKEN-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
os.environ.setdefault("BOT_USERNAME", "BerryBombOpsBot")
os.environ.setdefault("MINIAPP_SHORT_NAME", "ops")
os.environ.setdefault("ADMIN_TELEGRAM_USER_ID", "555000111")
os.environ.setdefault("STAFF_GROUP_CHAT_ID", "-1001234567890")
os.environ.setdefault("GOOGLE_SHEET_ID", "test-sheet")
os.environ.setdefault("GOOGLE_DRIVE_EVIDENCE_FOLDER_ID", "test-folder")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
os.environ.setdefault("APP_BASE_URL", "https://example.test")
os.environ.setdefault("SECRET_KEY", "x" * 80)
os.environ.setdefault("TIMEZONE", "Asia/Manila")
os.environ.setdefault("TEST_MODE", "true")
