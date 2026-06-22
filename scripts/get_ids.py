"""
Find your Telegram User ID and your group's chat ID — the beginner-friendly way.

How it works: it asks Telegram for recent messages your bot received
(getUpdates) and prints every person + chat it has seen.

Steps:
  1. DM your bot and send /start            -> reveals YOUR user id
  2. In your group send /start@<your_bot>   -> reveals the GROUP chat id
  3. Run:  python -m scripts.get_ids

NOTE: getUpdates only works when no webhook is set. This is fine before
deployment. After you go live with a webhook, you won't need this anymore.
"""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def main() -> None:
    r = httpx.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=20)
    data = r.json()
    if not data.get("ok"):
        print("Telegram error:", data)
        return

    users: dict[int, str] = {}
    chats: dict[int, str] = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("my_chat_member") or {}
        frm = msg.get("from") or {}
        if frm.get("id"):
            users[frm["id"]] = frm.get("first_name", "") + " @" + (frm.get("username") or "")
        chat = msg.get("chat") or {}
        if chat.get("id"):
            label = chat.get("title") or chat.get("first_name") or chat.get("type")
            chats[chat["id"]] = f"{label} ({chat.get('type')})"

    print("\n=== PEOPLE (your User ID is here) ===")
    for uid, name in users.items():
        print(f"  ADMIN_TELEGRAM_USER_ID = {uid}   # {name}")

    print("\n=== CHATS (your group ID starts with -100) ===")
    for cid, label in chats.items():
        print(f"  STAFF_GROUP_CHAT_ID = {cid}   # {label}")

    if not users and not chats:
        print("\nNothing yet. Make sure you:")
        print("  1) DM the bot /start")
        print("  2) Send /start@<your_bot> in the group")
        print("Then run this again.")


if __name__ == "__main__":
    main()
