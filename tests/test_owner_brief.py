"""Daily Owner Brief integration: success, retry-once, failure alert, config gate.
Fully mocked — never makes a real HTTP call or Telegram send."""
import asyncio

from app.services import owner_brief


class _Resp:
    def __init__(self, status, json_body=None, text=""):
        self.status_code = status
        self.reason_phrase = "OK" if status < 400 else "Server Error"
        self._json = json_body
        self.text = text

    @property
    def is_success(self):
        return self.status_code < 400

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _wire(monkeypatch, responses, sends):
    """responses: list of (_Resp or Exception) returned per attempt."""
    calls = {"n": 0}

    async def _post(send_email, day):
        i = calls["n"]
        calls["n"] += 1
        r = responses[min(i, len(responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(owner_brief, "_post_once", _post)

    async def _send(chat, text, reply_markup=None):
        sends.append(text)
    monkeypatch.setattr(owner_brief.notify, "send_message", _send)

    # Make it "configured" without real secrets.
    s = owner_brief.get_settings()
    monkeypatch.setattr(type(s), "owner_brief_configured", property(lambda self: True))
    monkeypatch.setattr(type(s), "owner_email_list", property(lambda self: ["a@b.com"]))
    return calls


def test_success_returns_text(monkeypatch):
    sends = []
    _wire(monkeypatch, [_Resp(200, {"telegram": "📦 Inventory OK"})], sends)
    res = asyncio.run(owner_brief.run_brief(send_email=True))
    assert res.ok and res.status == 200 and res.text == "📦 Inventory OK"
    assert sends == []  # no failure alert on success


def test_retry_then_success(monkeypatch):
    sends = []
    calls = _wire(monkeypatch, [_Resp(500), _Resp(200, {"text": "recovered"})], sends)
    res = asyncio.run(owner_brief.run_brief(send_email=True))
    assert res.ok and calls["n"] == 2 and res.text == "recovered"
    assert sends == []


def test_failure_after_retry_alerts(monkeypatch):
    sends = []
    calls = _wire(monkeypatch, [_Resp(500), _Resp(500)], sends)
    res = asyncio.run(owner_brief.run_brief(send_email=True))
    assert res.ok is False and calls["n"] == 2
    assert len(sends) == 1 and "failed" in sends[0].lower()  # owner alerted


def test_deliver_telegram_sends_text(monkeypatch):
    sends = []
    _wire(monkeypatch, [_Resp(200, {"telegram": "the report"})], sends)
    res = asyncio.run(owner_brief.run_brief(send_email=False, deliver_telegram=True))
    assert res.ok and sends == ["the report"]


def test_not_configured_is_noop(monkeypatch):
    sends = []

    async def _send(chat, text, reply_markup=None):
        sends.append(text)
    monkeypatch.setattr(owner_brief.notify, "send_message", _send)
    s = owner_brief.get_settings()
    monkeypatch.setattr(type(s), "owner_brief_configured", property(lambda self: False))
    res = asyncio.run(owner_brief.run_brief(send_email=True))
    assert res.ok is False and "not configured" in res.error.lower() and sends == []
