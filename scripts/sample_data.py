"""
Add sample staff + a schedule for today so you can test end-to-end.

    python -m scripts.sample_data <your_telegram_user_id>

In TEST_MODE the same Telegram User ID may back several sample staff (spec
section 31), so pass your own id and you can play every role.
"""
from __future__ import annotations

import sys

from app import clock, constants
from app.repositories import schedule_repo, staff_repo


def main() -> None:
    tg_id = sys.argv[1] if len(sys.argv) > 1 else "000000000"

    angel = staff_repo.find_active_by_name("Angel") or staff_repo.add_staff(
        "Angel", tg_id, role=constants.ROLE_OIC, username="angel")
    allyssa = staff_repo.find_active_by_name("Allyssa") or staff_repo.add_staff(
        "Allyssa", tg_id, role=constants.ROLE_STAFF, username="allyssa")
    staff_repo.find_active_by_name("Carol") or staff_repo.add_staff(
        "Carol", tg_id, role=constants.ROLE_STAFF, username="carol")

    # Ensure Angel is the OIC.
    staff_repo.assign_oic(angel["Staff ID"])

    today = clock.today()
    schedule_repo.upsert(today, status=constants.DAY_OPEN,
                         opener_staff_id=angel["Staff ID"],
                         closer_staff_id=allyssa["Staff ID"])
    print(f"Sample data ready. Opener=Angel, Closer=Allyssa for {today}.")
    print("All sample staff use Telegram id:", tg_id)


if __name__ == "__main__":
    main()
