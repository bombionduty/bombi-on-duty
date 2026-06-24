"""
In-memory draft store for the capture/confirm/edit flow.

A 'draft' is a batch of parsed tasks awaiting the owner's Confirm. Nothing here
ever writes to the sheet — tasks are only persisted by service.create_from_parsed
AFTER Confirm — so editing never saves prematurely, and Cancel simply discards.
Kept as pure functions so the flow is unit-testable without Telegram.
"""
from __future__ import annotations

import uuid

_drafts: dict[str, list] = {}
_meta: dict[str, dict] = {}   # batch -> {capture_chat, capture_msg, confirm_msg}


def create(tasks: list, capture_chat=None, capture_msg=None) -> str:
    bid = uuid.uuid4().hex[:8]
    _drafts[bid] = tasks
    _meta[bid] = {"capture_chat": capture_chat, "capture_msg": capture_msg,
                  "confirm_msg": None}
    return bid


def set_confirm_msg(bid: str, message_id) -> None:
    if bid in _meta:
        _meta[bid]["confirm_msg"] = message_id


def meta(bid: str) -> dict:
    return _meta.get(bid, {})


def get(bid: str):
    return _drafts.get(bid)


def exists(bid: str) -> bool:
    return bid in _drafts


def discard(bid: str) -> None:
    _drafts.pop(bid, None)


def pop(bid: str, default=None):
    _meta.pop(bid, None)
    return _drafts.pop(bid, default)


def edit_title(bid: str, idx: int, title: str) -> bool:
    d = _drafts.get(bid)
    if not d or idx >= len(d):
        return False
    d[idx]["title"] = title.strip() or d[idx]["title"]
    return True


def edit_date(bid: str, idx: int, iso: str) -> bool:
    d = _drafts.get(bid)
    if not d or idx >= len(d):
        return False
    d[idx]["due"] = iso or ""
    return True


def edit_who(bid: str, idx: int, who: str) -> bool:
    d = _drafts.get(bid)
    if not d or idx >= len(d):
        return False
    d[idx]["responsible"] = who
    return True


def apply_shared_date(bid: str, iso: str) -> bool:
    d = _drafts.get(bid)
    if not d:
        return False
    for t in d:
        if not t.get("due"):
            t["due"] = iso or ""
    return True


def undated_indices(bid: str) -> list:
    d = _drafts.get(bid) or []
    return [i for i, t in enumerate(d) if not t.get("due")]
