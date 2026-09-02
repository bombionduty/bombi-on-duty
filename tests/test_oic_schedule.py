"""OIC schedule access: the Store OIC may edit the schedule; other admin-only
endpoints stay blocked for the OIC."""
import pytest
from fastapi import HTTPException

from app import constants
from app.web import routes_miniapp as rm
from app.web.deps import Caller

ADMIN = Caller(tg_id=1, role=constants.ROLE_ADMIN, staff={"Staff Name": "Alicia"})
OIC = Caller(tg_id=2, role=constants.ROLE_OIC, staff={"Staff Name": "Angel"})
STAFF = Caller(tg_id=3, role=constants.ROLE_STAFF, staff={"Staff Name": "Carol"})


def test_schedule_editor_allows_admin_and_oic():
    assert rm._schedule_editor(ADMIN) is ADMIN
    assert rm._schedule_editor(OIC) is OIC


def test_schedule_editor_blocks_plain_staff():
    with pytest.raises(HTTPException) as e:
        rm._schedule_editor(STAFF)
    assert e.value.status_code == 403


def test_admin_only_still_blocks_oic():
    # Staff editing, checklists, settings, etc. remain admin-only.
    with pytest.raises(HTTPException) as e:
        rm._admin(OIC)
    assert e.value.status_code == 403
    assert rm._admin(ADMIN) is ADMIN


def test_caller_role_flags():
    assert OIC.is_oic and not OIC.is_admin
    assert ADMIN.is_admin and not ADMIN.is_oic
