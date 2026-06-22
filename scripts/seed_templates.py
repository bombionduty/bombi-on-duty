"""
Seed default checklist templates, timing, and settings (spec sections 10, 21).

Run after setup_sheet:
    python -m scripts.seed_templates

Idempotent-ish: it only seeds a section if that section is currently empty, so
re-running will not duplicate your data.
"""
from __future__ import annotations

from app import clock, constants
from app.repositories import checklist_repo, timing_repo
from app.repositories.misc_repo import settings_store
from app.sheets import client, schema

OPENING = constants.CHECK_OPENING
HANDOVER = constants.CHECK_HANDOVER
CLOSING = constants.CHECK_CLOSING

A = constants.ITEM_ATTESTATION
LIVE = constants.ITEM_LIVE_PHOTO
SHOT = constants.ITEM_SCREENSHOT

# (name, type, required)
DEFAULT_ITEMS = {
    OPENING: [
        ("Live team uniform photo", LIVE, True),
        ("Complete uniform for all staff currently on duty, including the opener", A, True),
        ("Berry Bomb shirt worn", A, True),
        ("Apron worn", A, True),
        ("Hair tied properly or in a bun when required", A, True),
        ("Proper bottoms and footwear", A, True),
        ("Storefront ready", A, True),
        ("Station clean and ready", A, True),
        ("Required equipment prepared", A, True),
        ("Important opening concerns identified", A, True),
    ],
    HANDOVER: [
        ("Screenshot: opening sales log sent to Sales Provider Viber GC", SHOT, True),
        ("Opening shift station properly turned over", A, True),
        ("Important issues communicated to the closer", A, True),
        ("Required opening records completed", A, True),
    ],
    CLOSING: [
        ("Screenshot: final sales log sent", SHOT, True),
        ("Screenshot: inventory completed or submitted", SHOT, True),
        ("Live store photo taken after lock-up", LIVE, True),
        ("Work area cleaned", A, True),
        ("Aircon turned off", A, True),
        ("Lights turned off", A, True),
        ("Signage turned off", A, True),
        ("Equipment and machines safely turned off", A, True),
        ("Final sales log completed", A, True),
        ("Inventory completed", A, True),
        ("Doors properly locked", A, True),
        ("Store left in proper condition", A, True),
        ("Important closing concerns recorded", A, True),
    ],
}

# Default times (Default day type). release, reminders, escalation, cutoff
DEFAULT_TIMING = {
    OPENING: ("12:00", "12:30", "13:00", "13:30"),
    HANDOVER: ("19:40", "19:55", "20:05", "20:15"),
    CLOSING: ("23:15", "23:35", "23:45", "23:55"),
}


def seed_items() -> None:
    if client.table(schema.CHECKLIST_TEMPLATES).all():
        print("  templates already present — skipping")
        return
    today = clock.today().isoformat()
    for ct, items in DEFAULT_ITEMS.items():
        for i, (name, itype, required) in enumerate(items):
            checklist_repo.add_item(ct, name, itype, required=required,
                                    sort_order=(i + 1) * 10,
                                    effective_from=today, created_by="seed")
        print(f"  seeded {len(items)} items for {ct}")


def seed_timing() -> None:
    if client.table(schema.CHECKLIST_TIMING).all():
        print("  timing already present — skipping")
        return
    for ct, (rel, rem, esc, cut) in DEFAULT_TIMING.items():
        timing_repo.upsert_default(ct, "Default", rel, rem, esc, cut)
        print(f"  seeded timing for {ct}")


def seed_settings() -> None:
    for key, value in constants.SETTING_DEFAULTS.items():
        if not client.table(schema.SETTINGS).find("Setting Key", key):
            settings_store.set(key, value, updated_by="seed")
    print("  seeded settings")


def main() -> None:
    seed_items()
    seed_timing()
    seed_settings()
    print("Seeding complete.")


if __name__ == "__main__":
    main()
