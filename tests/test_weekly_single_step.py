"""Single-photo weekly tasks: once the doer submits, it's DONE. A task set to
single-photo must never be flagged 'not verified by cutoff' — even for an
occurrence that was created earlier (the live definition wins)."""
from datetime import timedelta

import pytest

from app import clock
from app.services import weekly_service as ws


def test_requires_verify_reads_live_definition(monkeypatch):
    # The occurrence captured True at creation, but the task is now single-photo.
    inst = {"Weekly ID": "WK1", "Requires Verification": True}
    monkeypatch.setattr(ws.repo, "get_def", lambda wid: {"Requires Verification": False})
    assert ws._requires_verify(inst) is False          # live def wins

    # If the definition is gone, fall back to the instance's captured value.
    monkeypatch.setattr(ws.repo, "get_def", lambda wid: None)
    assert ws._requires_verify(inst) is True


@pytest.mark.asyncio
async def test_cutoff_completes_single_step_rather_than_flagging_missing(monkeypatch):
    inst = {
        "Instance ID": "I1", "Weekly ID": "WK1", "Status": ws.repo.ST_DOER_DONE,
        "Date": "2026-11-15", "Doer Name": "Angel",
        "Cutoff At": clock.iso(clock.now() - timedelta(hours=1)),  # cutoff passed
    }
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [inst])
    monkeypatch.setattr(ws.repo, "get_def", lambda wid: {"Requires Verification": False})
    updates = {}
    monkeypatch.setattr(ws.repo, "update_instance",
                        lambda iid, ch: updates.__setitem__(iid, ch))

    async def _noop(iid):
        return None

    monkeypatch.setattr(ws, "_refresh_card", _noop)

    flagged = await ws.cutoff_if_due(clock.now())
    assert flagged == []                                   # nothing missed
    assert updates["I1"]["Status"] == ws.repo.ST_VERIFIED  # completed instead


@pytest.mark.asyncio
async def test_cutoff_still_flags_two_step_unverified(monkeypatch):
    inst = {
        "Instance ID": "I2", "Weekly ID": "WK2", "Status": ws.repo.ST_DOER_DONE,
        "Date": "2026-11-15", "Doer Name": "Angel", "Doer Telegram User ID": "9",
        "Title": "Verify me", "Cutoff At": clock.iso(clock.now() - timedelta(hours=1)),
    }
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [inst])
    monkeypatch.setattr(ws.repo, "get_def", lambda wid: {"Requires Verification": True})
    monkeypatch.setattr(ws.repo, "update_instance", lambda iid, ch: None)

    async def _noop(iid):
        return None

    monkeypatch.setattr(ws, "_refresh_card", _noop)
    sent = []

    async def _send(chat, text, **kw):
        sent.append(text)

    monkeypatch.setattr(ws.notify, "send_message", _send)
    monkeypatch.setattr(ws.staff_repo, "oversight_target", lambda tg: (1, "OIC", "x"))

    flagged = await ws.cutoff_if_due(clock.now())
    assert len(flagged) == 1                               # genuinely missed
