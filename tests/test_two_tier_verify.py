"""Two-tier sign-off: on every submission BOTH the OIC and the admin get the
evidence pushed immediately, each with verify buttons (OIC tier-1, admin final)."""
import pytest

from app.services import summary_service as ss


class _S:
    admin_telegram_user_id = 999
    staff_group_chat_id = 111


@pytest.mark.asyncio
async def test_submission_pushes_evidence_and_buttons_to_both(monkeypatch):
    sent = []  # (chat_id, has_buttons)

    async def fake_send(chat, text, reply_markup=None, **kw):
        sent.append((chat, reply_markup is not None))

    async def fake_evidence(date_iso, ct=None, to_chat_id=None):
        sent.append((("EVIDENCE", to_chat_id), False))
        return 1

    monkeypatch.setattr(ss.notify, "send_message", fake_send)
    monkeypatch.setattr("app.services.evidence_delivery.send_evidence", fake_evidence)
    monkeypatch.setattr(ss.reviews, "add", lambda tid, reason: {"Review ID": "RV1"})
    monkeypatch.setattr(ss, "get_settings", lambda: _S())
    # OIC (Angel, tg 555) is distinct from the admin (999).
    monkeypatch.setattr(ss.staff_repo, "oversight_target", lambda tg: (555, "Angel", False))
    monkeypatch.setattr("app.repositories.evidence_repo.for_task", lambda tid: [])
    monkeypatch.setattr("app.repositories.task_repo.items_for", lambda tid: [])

    task = {"Task ID": "T1", "Date": "2026-11-18", "Checklist Type": "Closing Check",
            "Assigned Staff Name": "Carol", "Assigned Telegram User ID": "200",
            "Submitted At": "2026-11-18T23:00:00", "Checklist Result": "All Complete"}
    await ss.notify_submission(task, "Complete")

    chats_with_buttons = [c for c, b in sent if b]
    assert 555 in chats_with_buttons              # OIC got verify buttons
    assert 999 in chats_with_buttons              # admin got final-verify buttons
    # Evidence was pushed to BOTH the OIC and the admin.
    ev_targets = [c[1] for c, b in sent if isinstance(c, tuple) and c[0] == "EVIDENCE"]
    assert 555 in ev_targets and 999 in ev_targets


def test_admin_review_buttons_expose_decision_actions():
    from app.telegram import keyboards
    kb = keyboards.admin_review_buttons("RV1")
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "rev:ok:RV1" in datas        # approve / final sign-off
    assert "rev:reup:RV1" in datas      # ask for re-upload in group
    assert "rev:notdone:RV1" in datas   # mark not done
    assert "rev:view:RV1" in datas      # resend evidence


@pytest.mark.asyncio
async def test_request_reupload_posts_tagged_group_message(monkeypatch):
    from app.services import task_service as ts
    sent = []

    async def fake_send(chat, text, **kw):
        sent.append((chat, text))

    monkeypatch.setattr(ts.notify, "send_message", fake_send)
    monkeypatch.setattr(ts, "get_settings", lambda: _S())
    monkeypatch.setattr(ts, "with_mention", lambda t: {"_assignee_mention": "@carol"})
    updates = {}
    monkeypatch.setattr(ts.task_repo, "update",
                        lambda tid, ch: updates.__setitem__(tid, ch))

    await ts.request_reupload_in_group(
        {"Task ID": "T1", "Checklist Type": "Closing Check", "Assigned Staff Name": "Carol"})
    assert sent and sent[0][0] == _S.staff_group_chat_id
    assert "@carol" in sent[0][1] and "re-upload" in sent[0][1].lower()
    assert updates["T1"]["Review Required"] is True


@pytest.mark.asyncio
async def test_reupload_message_names_date_and_flagged_item(monkeypatch):
    from app.services import task_service as ts
    sent = []

    async def fake_send(chat, text, **kw):
        sent.append(text)

    monkeypatch.setattr(ts.notify, "send_message", fake_send)
    monkeypatch.setattr(ts, "get_settings", lambda: _S())
    monkeypatch.setattr(ts, "with_mention", lambda t: {"_assignee_mention": "@carol"})
    monkeypatch.setattr(ts.task_repo, "update", lambda tid, ch: None)
    monkeypatch.setattr("app.repositories.evidence_repo.for_task",
                        lambda tid: [{"Task Item ID": "I1", "Blank Photo": True}])
    monkeypatch.setattr(ts.task_repo, "get_item",
                        lambda iid: {"Item Name": "Take Photo of Store after Lock-up"})
    monkeypatch.setattr(ts, "missing_items", lambda tid: [])

    await ts.request_reupload_in_group(
        {"Task ID": "T1", "Checklist Type": "Closing Check",
         "Date": "2026-11-18", "Assigned Staff Name": "Carol"})
    msg = sent[0]
    assert "Take Photo of Store after Lock-up" in msg   # specific item
    assert "blank" in msg.lower()                        # the reason
    assert ("2026" in msg or "Nov" in msg)              # the date
    assert "@carol" in msg                               # tagged assignee


@pytest.mark.asyncio
async def test_single_tier_when_oic_is_admin(monkeypatch):
    sent = []

    async def fake_send(chat, text, reply_markup=None, **kw):
        sent.append((chat, reply_markup is not None))

    async def fake_evidence(date_iso, ct=None, to_chat_id=None):
        sent.append((("EVIDENCE", to_chat_id), False))
        return 1

    monkeypatch.setattr(ss.notify, "send_message", fake_send)
    monkeypatch.setattr("app.services.evidence_delivery.send_evidence", fake_evidence)
    monkeypatch.setattr(ss.reviews, "add", lambda tid, reason: {"Review ID": "RV1"})
    monkeypatch.setattr(ss, "get_settings", lambda: _S())
    # No distinct OIC → everything routes to the admin only.
    monkeypatch.setattr(ss.staff_repo, "oversight_target", lambda tg: (999, "Admin", True))
    monkeypatch.setattr("app.repositories.evidence_repo.for_task", lambda tid: [])
    monkeypatch.setattr("app.repositories.task_repo.items_for", lambda tid: [])

    task = {"Task ID": "T1", "Date": "2026-11-18", "Checklist Type": "Closing Check",
            "Assigned Staff Name": "Angel", "Assigned Telegram User ID": "555",
            "Submitted At": "2026-11-18T23:00:00", "Checklist Result": "All Complete"}
    await ss.notify_submission(task, "Complete")

    ev_targets = [c[1] for c, b in sent if isinstance(c, tuple) and c[0] == "EVIDENCE"]
    assert ev_targets == [999]                    # only the admin, once
