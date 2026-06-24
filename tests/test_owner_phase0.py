"""Phase 0 Owner Mode tests — plumbing + isolation, no live sheet needed."""
import asyncio

from app.owner import routing, scheduler
from app.sheets import schema


def test_owner_tabs_exist_and_separate():
    for tab in (schema.ADMIN_TASKS, schema.ADMIN_RECURRING,
                schema.ADMIN_SETTINGS, schema.ADMIN_HISTORY):
        assert tab in schema.HEADERS
        assert len(schema.HEADERS[tab]) > 0
    # Owner tabs must not collide with any staff tab name.
    staff_tabs = {schema.STAFF, schema.SCHEDULE, schema.TASKS, schema.TASK_ITEMS,
                  schema.EVIDENCE, schema.SETTINGS, schema.AUDIT_LOG}
    owner_tabs = {schema.ADMIN_TASKS, schema.ADMIN_RECURRING,
                  schema.ADMIN_SETTINGS, schema.ADMIN_HISTORY}
    assert staff_tabs.isdisjoint(owner_tabs)


def test_admin_user_guard():
    # conftest sets ADMIN_TELEGRAM_USER_ID=555000111
    assert routing.is_admin_user(555000111) is True
    assert routing.is_admin_user(999999999) is False
    assert routing.is_admin_user("not-a-number") is False


def test_staff_chat_guard():
    # conftest sets STAFF_GROUP_CHAT_ID=-1001234567890
    assert routing.is_staff_chat(-1001234567890) is True
    assert routing.is_staff_chat(-1) is False


def test_owner_tick_is_noop_and_safe():
    # Phase 0 tick returns None and never raises.
    assert asyncio.run(scheduler.owner_tick()) is None


def test_owner_handlers_register_callable():
    from app.owner import handlers
    assert callable(handlers.register)
