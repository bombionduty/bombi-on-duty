"""
Owner Mode routing + security guards.

These are the gates that keep Owner Mode and Staff Mode strictly separated:
  * is_admin_user  — only the configured admin Telegram id is the owner.
  * is_owner_chat  — only the registered Owner group counts as Owner Mode.
  * is_staff_chat  — the existing staff group (never Owner Mode).
"""
from __future__ import annotations

from app.config import get_settings
from app.owner import repo


def is_admin_user(user_id) -> bool:
    try:
        return int(user_id) == get_settings().admin_telegram_user_id
    except (TypeError, ValueError):
        return False


def owner_group_id() -> int | None:
    return repo.get_owner_group_id()


def is_owner_chat(chat_id) -> bool:
    gid = owner_group_id()
    return gid is not None and str(chat_id) == str(gid)


def is_staff_chat(chat_id) -> bool:
    return str(chat_id) == str(get_settings().staff_group_chat_id)


def capture_allowed(*, chat_id, user_id, is_bot: bool, has_text: bool) -> bool:
    """Whether a message may be captured as an owner task.

    Requires BOTH the registered owner chat AND the admin user, a real (non-bot)
    sender, and actual text (so service messages / channel posts / bot messages
    are ignored even if they reach the handler).
    """
    return bool(
        has_text and not is_bot
        and is_admin_user(user_id) and is_owner_chat(chat_id)
    )
