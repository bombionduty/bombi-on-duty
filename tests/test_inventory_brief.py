"""Inbound inventory-brief endpoint: token gate, destination, chunking."""
import asyncio

import pytest
from fastapi import HTTPException

from app.web import routes_inventory as ri


def _wire(monkeypatch, token="secret", chat=-100, sends=None):
    class _S:
        inventory_brief_token = token
        owner_telegram_chat_id = chat
    monkeypatch.setattr(ri, "get_settings", lambda: _S())

    class _Bot:
        async def send_message(self, chat_id, text, parse_mode=None, disable_web_page_preview=True):
            (sends if sends is not None else []).append((chat_id, text))
    monkeypatch.setattr(ri.notify, "bot", lambda: _Bot())


def test_chunks_splits_long_text():
    text = "\n".join(f"line {i}" for i in range(2000))  # well over 4000 chars
    parts = ri._chunks(text, size=4000)
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)
    assert "\n".join(parts).replace("\n", "") == text.replace("\n", "")


def test_rejects_bad_token(monkeypatch):
    sends = []
    _wire(monkeypatch, token="secret", sends=sends)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ri.inventory_brief({"token": "wrong", "text": "hi"}))
    assert e.value.status_code == 403 and sends == []


def test_posts_text_to_chat(monkeypatch):
    sends = []
    _wire(monkeypatch, token="secret", chat=-100200300, sends=sends)
    res = asyncio.run(ri.inventory_brief({"token": "secret", "text": "🫐 22 items critical"}))
    assert res["ok"] and res["messages_sent"] == 1
    assert sends[0][0] == -100200300 and "critical" in sends[0][1]


def test_empty_text_rejected(monkeypatch):
    _wire(monkeypatch, token="secret")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ri.inventory_brief({"token": "secret", "text": "   "}))
    assert e.value.status_code == 400


def test_not_configured_rejected(monkeypatch):
    _wire(monkeypatch, token=None)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ri.inventory_brief({"token": "x", "text": "hi"}))
    assert e.value.status_code == 503
