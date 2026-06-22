# Troubleshooting

Work top to bottom. Most problems are a missing environment variable or a
service account that wasn't shared.

## The bot doesn't respond to `/start`
- Confirm the app is running: open `https://<your-url>/healthz` → `{"status":"ok"}`.
- Webhook mode: on startup the log should say `Webhook set to .../telegram/webhook`.
  If not, check `APP_BASE_URL` is your real HTTPS URL with no trailing slash.
- Check the webhook health from Telegram:
  `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` — `last_error_message`
  tells you what Telegram saw. A 403 usually means the secret token mismatched;
  redeploy so `SECRET_KEY` is consistent.
- Quick local check: set `TELEGRAM_MODE=polling` and run `uvicorn app.main:app`.

## "Auth failed" / "Not an authorised user" in a Mini App
- The Mini App must be opened **from Telegram** (so `initData` exists), not in a
  normal browser tab.
- For staff: their numeric Telegram User ID must exist and be **Active** in the
  `Staff` tab. Add them via Admin → Staff or `/addstaff <name> <id>`.
- For admin: `ADMIN_TELEGRAM_USER_ID` must equal your numeric id from
  @userinfobot.

## "This checklist is assigned to …"
- Working as intended: only the assigned opener/closer (or admin) can submit a
  task. Reassign in Admin → Today, or check the `Schedule` tab.

## Google Sheets errors (PermissionDenied / 404)
- Share the **Sheet** AND the **Drive folder** with the service account
  `client_email` as **Editor** (§3.7 in README).
- Confirm `GOOGLE_SHEET_ID` and `GOOGLE_DRIVE_EVIDENCE_FOLDER_ID` are the id
  parts of the URLs, not the whole URL.
- Enable both **Google Sheets API** and **Google Drive API** in the Cloud project.
- "Worksheet not found" → run `python -m scripts.setup_sheet`.

## `service_account.json not found`
- Locally: the file must sit next to `requirements.txt`, named exactly
  `service_account.json`.
- On Render: don't upload the file — paste its full contents into the
  `GOOGLE_SERVICE_ACCOUNT_JSON` env var instead.

## Live camera doesn't open
- Cameras require HTTPS — works once deployed, not over plain `http://localhost`.
- If the phone denies permission, the app shows a **gallery upload** fallback and
  records the capture source as *Gallery Fallback* (marked Review Recommended for
  live-photo items). Test on real iPhone and Android Telegram apps.

## Images don't show in the Admin evidence gallery
- Evidence is private and authenticated; the `<img>` URL carries `?auth=<initData>`.
  Open the gallery **inside Telegram**, not a plain browser.
- If you see a 502 on an image, the Drive download failed — check the folder is
  shared with the service account.

## Reminders fire late or not at all
- On Render free tier the service sleeps; keep it awake (README §9) or use the
  paid plan.
- The scheduler ticks every minute; an action only fires when its configured time
  passes **and** the task is still incomplete. Check the `Checklist Timing` tab.

## Duplicate messages after a restart
- Should not happen: every timed action is recorded in the **Audit Log** as a
  `scheduler_marker`. If you wiped the Audit Log tab, the ledger resets — don't
  delete that tab.

## A staff member submitted but the group card still says Pending
- The card edits in place; if the bot lost admin rights in the group it can't
  edit. Re-grant the bot **admin** in the group.

## Reset for a clean test
- Duplicate the Sheet (or make a separate test Sheet) and point
  `GOOGLE_SHEET_ID` at it with `TEST_MODE=true`, a test group, and a test Drive
  folder. Never test against production data.
