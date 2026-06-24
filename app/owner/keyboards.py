"""Owner Mode inline keyboards. All callback data is prefixed 'own:'."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_kb(batch_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"own:cf:{batch_id}")],
        [InlineKeyboardButton("✏️ Edit", callback_data=f"own:ed:{batch_id}")],
        [InlineKeyboardButton("🗑 Cancel", callback_data=f"own:cx:{batch_id}")],
    ])


def nodate_kb(batch_id: str) -> InlineKeyboardMarkup:
    opts = [("Today", "today"), ("Tomorrow", "tom"), ("This Week", "week"),
            ("Next Week", "next"), ("No Deadline", "none"), ("📅 Choose Date", "choose")]
    rows = [[InlineKeyboardButton(lbl, callback_data=f"own:nd:{batch_id}:{key}")]
            for lbl, key in opts]
    return InlineKeyboardMarkup(rows)


# ---- Edit flow (correct a parsed batch before saving) ----
def edit_list_kb(batch_id: str, tasks: list) -> InlineKeyboardMarkup:
    rows = []
    for i, t in enumerate(tasks):
        title = (t.get("title") or "")[:30]
        rows.append([InlineKeyboardButton(f"{i + 1}. {title}",
                                          callback_data=f"own:ei:{batch_id}:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"own:ebk:{batch_id}")])
    return InlineKeyboardMarkup(rows)


def edit_task_kb(batch_id: str, idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Title", callback_data=f"own:et:{batch_id}:{idx}"),
         InlineKeyboardButton("📅 Date", callback_data=f"own:edt:{batch_id}:{idx}")],
        [InlineKeyboardButton("👤 Responsible", callback_data=f"own:ewho:{batch_id}:{idx}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"own:ed:{batch_id}")],
    ])


def edit_date_kb(batch_id: str, idx: int) -> InlineKeyboardMarkup:
    opts = [("Today", "today"), ("Tomorrow", "tom"), ("In 2 Days", "2d"),
            ("This Weekend", "wknd"), ("Next Week", "next"), ("No Deadline", "none"),
            ("📅 Choose Date", "choose")]
    rows = [[InlineKeyboardButton(lbl, callback_data=f"own:eds:{batch_id}:{idx}:{key}")]
            for lbl, key in opts]
    return InlineKeyboardMarkup(rows)


def edit_who_kb(batch_id: str, idx: int) -> InlineKeyboardMarkup:
    opts = [("Me", ""), ("Alex", "Alex"), ("Accountant", "Accountant"),
            ("Finance", "Finance")]
    rows = [[InlineKeyboardButton(lbl or "Me",
             callback_data=f"own:ews:{batch_id}:{idx}:{val or 'me'}")]
            for lbl, val in opts]
    return InlineKeyboardMarkup(rows)


def task_kb(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Done", callback_data=f"own:dn:{task_id}"),
         InlineKeyboardButton("📅 Reschedule", callback_data=f"own:rs:{task_id}")],
        [InlineKeyboardButton("🔵 Waiting", callback_data=f"own:wt:{task_id}"),
         InlineKeyboardButton("🗑 Skip", callback_data=f"own:sk:{task_id}")],
    ])


def reschedule_kb(task_id: str) -> InlineKeyboardMarkup:
    opts = [("Later Today", "today"), ("Tomorrow", "tom"), ("In 2 Days", "2d"),
            ("This Weekend", "wknd"), ("Next Week", "next")]
    rows = [[InlineKeyboardButton(lbl, callback_data=f"own:rx:{task_id}:{key}")]
            for lbl, key in opts]
    return InlineKeyboardMarkup(rows)


def waiting_kb(task_id: str) -> InlineKeyboardMarkup:
    opts = [("Follow up tomorrow", "tom"), ("In 2 days", "2d"), ("Next week", "next")]
    rows = [[InlineKeyboardButton(lbl, callback_data=f"own:wx:{task_id}:{key}")]
            for lbl, key in opts]
    return InlineKeyboardMarkup(rows)


def dashboard_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Task", callback_data="own:hint:add")],
        [InlineKeyboardButton("📋 Refresh", callback_data="own:dash:refresh")],
    ])
