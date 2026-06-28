"""Inline keyboards and Mini App launch buttons."""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from app.config import get_settings


def open_checklist_button(task_token: str) -> InlineKeyboardMarkup:
    """Group/staff button that deep-links the Mini App straight to the task.

    Inside a group we use a normal URL deep link (t.me/bot/app?startapp=TOKEN)
    because group messages cannot host a web_app button reliably.
    """
    url = get_settings().miniapp_deeplink(task_token)
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📋 Open Checklist", url=url)]]
    )


def assignment_done_button(assignment_id: str) -> InlineKeyboardMarkup:
    """Group button for an ad-hoc staff assignment — the assignee taps to complete."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Mark Done", callback_data=f"asgn:done:{assignment_id}")]]
    )


def admin_controls_button() -> InlineKeyboardMarkup:
    """Private-chat web_app button that opens the Admin Mini App."""
    url = get_settings().admin_miniapp_url
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚙️ Admin Controls", web_app=WebAppInfo(url=url))]]
    )


def oic_followup_buttons(task_id: str, allow_recovery: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("👁 View Task", callback_data=f"oic:view:{task_id}")],
        [InlineKeyboardButton("✉️ Message Staff", callback_data=f"oic:msg:{task_id}")],
    ]
    if allow_recovery:
        url = get_settings().miniapp_deeplink(f"recovery_{task_id}")
        rows.append([InlineKeyboardButton("➕ Complete Missing Entry", url=url)])
    return InlineKeyboardMarkup(rows)


def review_buttons(review_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Looks Complete", callback_data=f"rev:ok:{review_id}")],
        [InlineKeyboardButton("⚠️ Mark Incomplete", callback_data=f"rev:follow:{review_id}")],
        [InlineKeyboardButton("👁 Resend Evidence", callback_data=f"rev:view:{review_id}")],
    ])


def announcement_ack_button(announcement_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Noted", callback_data=f"ack:{announcement_id}")]]
    )


def summary_buttons(date_iso: str) -> InlineKeyboardMarkup:
    admin_url = get_settings().admin_miniapp_url + f"?page=evidence&date={date_iso}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 View All Evidence", web_app=__webapp(admin_url))],
        [InlineKeyboardButton("📤 Send Evidence Here", callback_data=f"sendev:all:{date_iso}")],
        [
            InlineKeyboardButton("Opening", callback_data=f"sendev:Opening Check:{date_iso}"),
            InlineKeyboardButton("Handover", callback_data=f"sendev:Opener Handover:{date_iso}"),
            InlineKeyboardButton("Closing", callback_data=f"sendev:Closing Check:{date_iso}"),
        ],
        [InlineKeyboardButton("📊 Open Daily Report", web_app=__webapp(
            get_settings().admin_miniapp_url + f"?page=today&date={date_iso}"))],
    ])


def __webapp(url: str) -> WebAppInfo:
    return WebAppInfo(url=url)
