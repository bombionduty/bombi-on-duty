# Berry Bomb Daily Operations — Telegram Bot + Mini Apps

A complete daily-operations system for the Berry Bomb shop. Staff complete one
simple checklist per checkpoint (Opening, Handover, Closing) inside a Telegram
Mini App; the system tracks accountability, escalates to the Store OIC, supports
a transparent OIC recovery flow, and sends you private daily/weekly summaries
with one-tap access to all submitted evidence.

> **You are the Admin.** Everything is controlled from your private chat with the
> bot and the Admin Mini App. Staff only ever see their checklist buttons in the
> Staff Daily Ops group.

---

## 1. What you get

| Piece | Where it lives |
|---|---|
| Telegram bot (webhook) | `app/telegram/`, `app/main.py` |
| Staff Mini App (checklists + live camera) | `app/static/staff/` |
| Admin Mini App (12 pages) | `app/static/admin/` |
| Scheduler (reminders, escalation, cutoff, summaries) | `app/scheduler/` |
| Google Sheets data store (repository layer) | `app/repositories/`, `app/sheets/` |
| Google Drive evidence storage | `app/services/drive_service.py` |
| Evidence processing (EXIF, hashes, duplicate, footer) | `app/services/evidence_service.py` |
| Setup + seed + sample scripts | `scripts/` |
| Tests | `tests/` |

**Version 1 decisions** (chosen for simplicity + reliability, all editable later):

- **Storage:** Google Sheets (free, you can read/edit it by hand) wrapped in a
  repository layer so it can be swapped for a real database later.
- **Evidence files:** Google Drive (private, never public links).
- **Scheduler:** one APScheduler job that ticks every minute in Asia/Manila.
- **Hosting:** Render.com (free HTTPS). Honest limits explained in §9.
- **No paid AI APIs, no React build system, no extra platforms.**

---

## 2. Before you start — accounts you need

1. A **Telegram** account (you already have one).
2. A **Google** account (for Sheets + Drive).
3. A free **Render.com** account (for hosting) — or any host that gives HTTPS.

You do **not** need to know how to code. Copy/paste the commands exactly.

---

## 3. Step-by-step setup

### 3.1 Create the Telegram bot

1. In Telegram, open **@BotFather**.
2. Send `/newbot`. Choose a name (e.g. `Berry Bomb Ops`) and a username ending in
   `bot` (e.g. `BerryBombOpsBot`).
3. BotFather gives you a **token** like `123456789:AAE...`. Copy it — this is your
   `TELEGRAM_BOT_TOKEN`. Keep it secret.

### 3.2 Create the Mini App short name

1. Still in **@BotFather**, send `/newapp` and pick your bot.
2. Give it a title, description, and a 512×512 photo (any image).
3. When asked for the **Web App URL**, enter (you will fix this after deploying):
   `https://your-app.onrender.com/static/staff/index.html`
4. When asked for a **short name**, type `ops`. This is your `MINIAPP_SHORT_NAME`.
   - The staff deep link becomes `https://t.me/<YourBot>/ops?startapp=<token>`.

### 3.3 Get your numeric Telegram User ID

1. Open **@userinfobot** and press start. It replies with your numeric **Id**.
2. That number is your `ADMIN_TELEGRAM_USER_ID`.

### 3.4 Create the Staff Daily Ops group and get its ID

1. Create a normal Telegram **group** named "Berry Bomb Daily Ops".
2. Add your bot to the group, then make the bot an **admin** of the group
   (so it can post and edit messages). Do **not** enable Topics.
3. To get the group's numeric id: temporarily add **@RawDataBot** (or
   **@getidsbot**) to the group; it prints a chat id like `-1001234567890`.
   That is your `STAFF_GROUP_CHAT_ID`. Remove the helper bot afterward.

### 3.5 Create the Google Sheet

1. Go to <https://sheets.google.com> → **Blank** spreadsheet.
2. Name it "Berry Bomb Ops Data".
3. The id is the long string in the URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit` →
   this is `GOOGLE_SHEET_ID`.

### 3.6 Create the Google Drive evidence folder

1. Go to <https://drive.google.com> → **New → Folder** → "Berry Bomb Ops Evidence".
2. Open the folder; the id is in the URL after `/folders/` →
   `GOOGLE_DRIVE_EVIDENCE_FOLDER_ID`.

### 3.7 Create a Google Service Account (lets the bot read/write Sheets + Drive)

1. Go to <https://console.cloud.google.com> → create/select any project.
2. **APIs & Services → Library** → enable **Google Sheets API** and
   **Google Drive API**.
3. **APIs & Services → Credentials → Create Credentials → Service account**.
   Give it a name, click through, **Done**.
4. Click the new service account → **Keys → Add key → Create new key → JSON**.
   A `*.json` file downloads. Rename it to **`service_account.json`** and put it
   in the project folder (next to `requirements.txt`).
5. Open that JSON and copy the `client_email` value (looks like
   `something@project.iam.gserviceaccount.com`).
6. **Share access** so the bot can use them:
   - Open your Google **Sheet** → **Share** → paste the `client_email` → give
     **Editor** → Send.
   - Open your Drive **evidence folder** → **Share** → paste the same email →
     **Editor** → Send.

### 3.8 Fill in your environment file

```bash
cp .env.example .env
```

Open `.env` and paste every value you collected above. Generate the secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste that as `SECRET_KEY`. Set `APP_BASE_URL` after you deploy (§8).

---

## 4. Install and initialize (local)

> Requires **Python 3.10+** (the project targets 3.12; it also runs on 3.9).
> Check with `python3 --version`.

```bash
# 1. Create an isolated environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Build all the Google Sheet tabs + headers
python -m scripts.setup_sheet

# 4. Seed default checklists, timings, and settings
python -m scripts.seed_templates

# 5. (Optional) add sample staff + today's schedule for testing.
#    Pass YOUR telegram user id so you can play every role.
python -m scripts.sample_data 123456789
```

Open your Google Sheet — you should now see all the tabs (Staff, Schedule,
Tasks, Evidence, …) with headers, plus the seeded checklist items and timings.

---

## 5. Run it locally (quick test, no public URL)

For a fast local smoke test you can use **polling** mode (no HTTPS needed):

```bash
# In .env set:  TELEGRAM_MODE=polling
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Then message your bot `/start` in Telegram. As admin you'll get the **Admin
Controls** button. Note: Mini Apps need HTTPS, so the *buttons* work fully only
after you deploy (§8). Polling is mainly for testing commands and the scheduler.

Health check: open <http://localhost:8000/healthz> → `{"status":"ok"}`.

Run the tests anytime:

```bash
pytest -q
```

---

## 6. How staff use it (daily flow)

1. At the configured **release time** the bot posts one card in the group, e.g.
   *Opening Check — Assigned opener: Angel — Due by 1:30 PM* with an
   **Open Checklist** button.
2. The assigned staff taps it → the Mini App opens straight to **their** task.
3. They complete required proof (live camera photo / screenshot / number / text)
   and confirm the attestation list with **Everything Listed Is Complete** or
   **Report an Issue**.
4. They tap **Submit**. The group card updates to *Submitted On Time*.

If they don't finish in time, the bot reminds them (listing only what's missing),
then privately escalates to the **Store OIC**, then marks the task
**Not Submitted** at cutoff — and the OIC can later run a transparent
**OIC Recovery** without erasing the original record.

---

## 7. How you (Admin) use it

- **Private chat → Admin Controls** opens the Admin Mini App (Today, Schedule,
  Staff, Checklists, Timing, Evidence, Recoveries, OIC Reviews, Announcements,
  Reports, Settings, Test).
- Or use chat commands (full list: `/help`). Examples:
  - `/opener Carol today` · `/closer Allyssa tomorrow`
  - `/closed today` · `/open tomorrow` · `/copyweek`
  - `/addstaff Carol 123456789` · `/removestaff Carol`
  - `/announce Complete uniform is required every shift.`
  - `/summary today` · `/test summary`
- The **Daily Summary** (00:05 Manila by default) arrives privately with
  **View All Evidence** and **Send Evidence Here** buttons.

---

## 8. Deploy to Render.com (production, free HTTPS)

1. Put this project in a **GitHub** repo (private is fine). **Do not commit
   `.env` or `service_account.json`** — they're already in `.gitignore`.
2. On Render: **New → Blueprint**, point it at your repo. Render reads
   `render.yaml`.
3. In the service **Environment** tab, set every variable from your `.env`.
   - For Google credentials on Render, **do not upload the file**. Instead set
     `GOOGLE_SERVICE_ACCOUNT_JSON` to the entire contents of
     `service_account.json` (open it, copy everything, paste as the value).
   - Set `TELEGRAM_MODE=webhook` and `TEST_MODE=false` for production.
4. Deploy. Render gives you a URL like `https://berry-bomb-ops.onrender.com`.
5. Set `APP_BASE_URL` to that URL (no trailing slash) and redeploy. On startup
   the app automatically registers the Telegram webhook.
6. Go back to **@BotFather → /myapps**, edit your Mini App **Web App URL** to:
   `https://berry-bomb-ops.onrender.com/static/staff/index.html`.

Verify: open `https://<your-url>/healthz` → `{"status":"ok"}`.

---

## 9. Honest hosting limitations

- Render's **free** web service **sleeps** after ~15 min idle and takes ~30s to
  wake. A reminder due during sleep can fire a little late. Two fixes:
  1. Use the **starter** (paid, always-on) plan — set in `render.yaml`, or
  2. Keep the free plan awake with a free pinger (e.g. **cron-job.org**) hitting
     `https://<your-url>/healthz` every 5 minutes.
- The scheduler runs **inside** the web process. If the host restarts, the
  markers ledger (stored in the Audit Log tab) prevents any duplicate reminder,
  escalation, cutoff, or summary — it is safe to restart.
- Google Sheets has API rate limits. For one shop this is fine; reads are cached
  for a few seconds.

---

## 10. Testing procedure

See **`TROUBLESHOOTING.md`** for fixes and **`LAUNCH_CHECKLIST.md`** for the full
go-live checklist. Quick manual test in `TEST_MODE=true`:

1. `python -m scripts.sample_data <your_id>` (you become Angel=OIC and Allyssa).
2. In the Admin Mini App → **Test → Release Today's Tasks** (or `/test opening`).
3. Tap **Open Checklist** in the group, capture a live photo, submit.
4. Try opening a task you're *not* assigned (as a different staff record) → you
   should see the "assigned to …" rejection.
5. **Test → Send Today's Summary** → you get the summary with evidence buttons.
6. Tap **Send Evidence Here** → images arrive in your private chat with captions.

---

## 11. Project layout

```
berry-bomb-ops/
├── app/
│   ├── main.py            # FastAPI app: webhook, API, static, scheduler, health
│   ├── config.py          # env-var settings (validated)
│   ├── clock.py           # Asia/Manila time helpers
│   ├── constants.py       # status vocabularies, item types, setting keys
│   ├── security.py        # initData validation + task-token hashing
│   ├── sheets/            # schema + generic Google Sheets table wrapper
│   ├── repositories/      # one module per data tab (the swappable seam)
│   ├── services/          # business logic (tasks, evidence, recovery, summaries)
│   ├── telegram/          # bot, handlers, message/keyboard builders, notify
│   ├── scheduler/         # 1-minute tick + jobs
│   ├── web/               # FastAPI routes + auth deps
│   └── static/            # staff + admin Mini App frontends (plain HTML/CSS/JS)
├── scripts/               # setup_sheet, seed_templates, sample_data
├── tests/                 # pytest suite (pure logic, no network)
├── requirements.txt  .env.example  .gitignore  Dockerfile  render.yaml
└── README.md  TROUBLESHOOTING.md  LAUNCH_CHECKLIST.md
```

---

## 12. Changing things later (all editable, no code edits)

- **Times / reminders / cutoffs:** Admin Mini App → **Timing**, or the
  `Checklist Timing` sheet tab. Supports Default / Weekday / Weekend and
  date-specific overrides (`Timing Overrides` tab).
- **Checklist items:** Admin Mini App → **Checklists** (add / archive / set proof
  type / required / effective dates / weekdays).
- **Who is OIC:** Admin Mini App → **Staff → Make Store OIC** (not hard-coded).
- **Recovery window, summary time, retention, spot checks:** Admin → **Settings**.

Every change is written to the **Audit Log** tab.
