"""
Smaller repositories grouped together: OIC Recoveries, Notes, Announcements,
Acknowledgements, OIC Reviews, Settings, Audit Log.

Each is a thin wrapper over its sheet tab (spec section 40).
"""
from __future__ import annotations

from datetime import date

from app import clock, constants
from app.repositories.base import as_bool, gen_id, now_iso
from app.sheets import client, schema


# ----------------------------------------------------------- OIC Recoveries
class recovery:
    @staticmethod
    def _t():
        return client.table(schema.OIC_RECOVERIES)

    @staticmethod
    def add(row: dict) -> dict:
        row.setdefault("Recovery ID", gen_id("REC"))
        row.setdefault("Recovery Submitted At", now_iso())
        return recovery._t().append(row)

    @staticmethod
    def for_task(task_id: str) -> dict | None:
        return recovery._t().find("Task ID", task_id)

    @staticmethod
    def for_date(d: date) -> list[dict]:
        return recovery._t().find_all("Operating Date", d.isoformat())

    @staticmethod
    def between(start: date, end: date) -> list[dict]:
        out = []
        for r in recovery._t().all():
            try:
                od = clock.parse_date(str(r.get("Operating Date")))
            except (ValueError, TypeError):
                continue
            if start <= od <= end:
                out.append(r)
        return out


# ------------------------------------------------------------------- Notes
class notes:
    @staticmethod
    def _t():
        return client.table(schema.NOTES)

    @staticmethod
    def add(sender: dict, text: str, related_task_id: str = "") -> dict:
        row = {
            "Note ID": gen_id("NOTE"),
            "Timestamp": now_iso(),
            "Date": clock.today().isoformat(),
            "Reported By Staff ID": sender.get("Staff ID", ""),
            "Reported By Name": sender.get("Staff Name", ""),
            "Reported By Telegram User ID": str(sender.get("Telegram User ID", "")),
            "Note": text,
            "Related Task ID": related_task_id,
            "Follow-Up Status": "Open",
        }
        return notes._t().append(row)

    @staticmethod
    def for_date(d: date) -> list[dict]:
        return notes._t().find_all("Date", d.isoformat())


# ----------------------------------------------------------- Announcements
class announcements:
    @staticmethod
    def _t():
        return client.table(schema.ANNOUNCEMENTS)

    @staticmethod
    def _acks():
        return client.table(schema.ACKNOWLEDGEMENTS)

    @staticmethod
    def add(message: str, posted_by: str, telegram_message_id: int | str) -> dict:
        row = {
            "Announcement ID": gen_id("ANN"),
            "Message": message,
            "Posted At": now_iso(),
            "Posted By": posted_by,
            "Telegram Message ID": str(telegram_message_id),
            "Active": True,
        }
        return announcements._t().append(row)

    @staticmethod
    def get(announcement_id: str) -> dict | None:
        return announcements._t().find("Announcement ID", announcement_id)

    @staticmethod
    def acknowledge(announcement_id: str, staff: dict) -> bool:
        """Idempotent: clicking twice does not duplicate (spec section 38)."""
        existing = [
            a for a in announcements._acks().find_all("Announcement ID", announcement_id)
            if str(a.get("Telegram User ID")) == str(staff.get("Telegram User ID"))
        ]
        if existing:
            return False
        announcements._acks().append({
            "Announcement ID": announcement_id,
            "Staff ID": staff.get("Staff ID", ""),
            "Staff Name": staff.get("Staff Name", ""),
            "Telegram User ID": str(staff.get("Telegram User ID", "")),
            "Acknowledged At": now_iso(),
        })
        return True

    @staticmethod
    def ack_user_ids(announcement_id: str) -> set[str]:
        return {
            str(a.get("Telegram User ID"))
            for a in announcements._acks().find_all("Announcement ID", announcement_id)
        }


# ------------------------------------------------------------- OIC Reviews
class reviews:
    @staticmethod
    def _t():
        return client.table(schema.OIC_REVIEWS)

    @staticmethod
    def add(task_id: str, reason: str, evidence_id: str = "", oic_staff_id: str = "") -> dict:
        row = {
            "Review ID": gen_id("RV"),
            "Task ID": task_id,
            "Evidence ID": evidence_id,
            "Assigned OIC Staff ID": oic_staff_id,
            "Review Reason": reason,
            "Review Status": "Pending",
            "Reviewer Telegram User ID": "",
            "Review Notes": "",
            "Requested At": now_iso(),
            "Reviewed At": "",
        }
        return reviews._t().append(row)

    @staticmethod
    def get(review_id: str) -> dict | None:
        return reviews._t().find("Review ID", review_id)

    @staticmethod
    def resolve(review_id: str, reviewer_tg_id: int, status: str, notes: str = "") -> bool:
        return reviews._t().update("Review ID", review_id, {
            "Review Status": status,
            "Reviewer Telegram User ID": str(reviewer_tg_id),
            "Review Notes": notes,
            "Reviewed At": now_iso(),
        })


# --------------------------------------------------------------- Settings
class settings_store:
    @staticmethod
    def _t():
        return client.table(schema.SETTINGS)

    @staticmethod
    def get(key: str, default: str | None = None) -> str:
        row = settings_store._t().find("Setting Key", key)
        if row and str(row.get("Setting Value")) != "":
            return str(row.get("Setting Value"))
        return default if default is not None else constants.SETTING_DEFAULTS.get(key, "")

    @staticmethod
    def get_int(key: str) -> int:
        try:
            return int(settings_store.get(key))
        except (ValueError, TypeError):
            return int(constants.SETTING_DEFAULTS.get(key, "0"))

    @staticmethod
    def get_bool(key: str) -> bool:
        return as_bool(settings_store.get(key))

    @staticmethod
    def set(key: str, value: str, updated_by: str = "") -> None:
        t = settings_store._t()
        if t.find("Setting Key", key):
            t.update("Setting Key", key, {
                "Setting Value": value, "Updated At": now_iso(), "Updated By": updated_by,
            })
        else:
            t.append({
                "Setting Key": key, "Setting Value": value, "Description": "",
                "Updated At": now_iso(), "Updated By": updated_by,
            })


# -------------------------------------------------------------- Audit Log
class audit:
    @staticmethod
    def _t():
        return client.table(schema.AUDIT_LOG)

    @staticmethod
    def log(
        actor_tg_id: int | str,
        actor_name: str,
        actor_role: str,
        action: str,
        entity_type: str = "",
        entity_id: str = "",
        *,
        original_staff_id: str = "",
        previous_value: str = "",
        new_value: str = "",
        reason: str = "",
    ) -> None:
        audit._t().append({
            "Audit ID": gen_id("AUD"),
            "Timestamp": now_iso(),
            "Actor Telegram User ID": str(actor_tg_id),
            "Actor Name": actor_name,
            "Actor Role": actor_role,
            "Action": action,
            "Entity Type": entity_type,
            "Entity ID": entity_id,
            "Original Assigned Staff ID": original_staff_id,
            "Previous Value": previous_value,
            "New Value": new_value,
            "Reason": reason,
        })
