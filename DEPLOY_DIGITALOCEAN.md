# Deploy Bombi On Duty to DigitalOcean App Platform

This runs the bot 24/7 with a free `https://` URL (required by Telegram).
Total time: ~20 minutes. You only do this once.

---

## Part A — Put the code on GitHub (App Platform deploys from GitHub)

1. Make a free account at https://github.com if you don't have one.
2. Create a **new, empty, private** repository named `bombi-on-duty`.
   - Do **not** add a README, .gitignore, or license (we already have them).
3. Tell Claude the repo URL, or push it yourself:
   ```bash
   cd berry-bomb-ops
   git remote add origin https://github.com/<your-username>/bombi-on-duty.git
   git push -u origin main
   ```
   GitHub will ask for your username + a **Personal Access Token** (not your
   password). Create one at: GitHub → Settings → Developer settings →
   Personal access tokens → Tokens (classic) → Generate, with `repo` scope.

> Your secrets are NOT in this repo — `.env` and `service_account.json` are
> gitignored. We add secrets directly in DigitalOcean in Part B.

---

## Part B — Create the App on DigitalOcean

1. Go to https://cloud.digitalocean.com/apps → **Create App**.
2. **Service Provider:** GitHub → authorise → pick your `bombi-on-duty` repo,
   branch `main`. DigitalOcean auto-detects the **Dockerfile**.
3. **Region:** choose **Singapore (SGP)** (closest to the Philippines).
4. **Plan:** Basic. Pick the smallest instance (**basic-xxs**). It runs 24/7.
5. **Edit the web service → HTTP port:** set to **8080**.
6. **Environment Variables:** open `DEPLOY_SECRETS.local.txt` (Claude made it)
   and add each line. Mark them **Encrypted**. Then also add these plain ones:

   | Key | Value |
   |-----|-------|
   | `APP_BASE_URL` | `${APP_URL}` |
   | `TIMEZONE` | `Asia/Manila` |
   | `TEST_MODE` | `false` |
   | `ENVIRONMENT_NAME` | `production` |
   | `TELEGRAM_MODE` | `webhook` |
   | `MINIAPP_SHORT_NAME` | `ops` |
   | `PORT` | `8080` |

   (`${APP_URL}` is a DigitalOcean built-in that becomes your real app URL.)
7. Click **Create Resources**. Wait for the build (~3–5 min) until it says
   **"Deployed successfully"** with a green check.
8. Copy your app URL, e.g. `https://bombi-on-duty-abcde.ondigitalocean.app`.
9. Open `https://<your-app-url>/healthz` in a browser. You should see
   `{"status":"ok"}`. The bot has now switched itself to webhook mode.

---

## Part C — Register the Mini App in BotFather (one time)

This makes the "Open Checklist" button actually open the form.

1. In Telegram, open **@BotFather** → send `/newapp`.
2. Select **@bombi_ondutybot**.
3. **Title:** `Bombi On Duty`
4. **Description:** `Daily opening, handover, and closing checklists.`
5. **Photo:** upload any 640×360 image (a logo is fine).
6. **Web App URL:** `https://<your-app-url>/static/staff/index.html`
7. **Short name:** `ops`  ← must match `MINIAPP_SHORT_NAME`.

That's it. The group button `t.me/bombi_ondutybot/ops?startapp=...` now opens the
staff checklist, and the **Admin Controls** button (in your private chat after
`/start`) opens the admin Mini App.

---

## Part D — Go-live checks

- DM the bot `/start` → tap **Admin Controls** → the admin app should load.
- In the group, tap **Open Checklist** on the posted card → the form opens,
  the live camera works, and submitting updates the group card.
- Send `/summary today` to yourself to see the daily summary with evidence
  buttons.

If anything misbehaves, see `TROUBLESHOOTING.md`.

---

## Rolling back / updating

- **Update the app:** commit + `git push`. App Platform auto-redeploys.
- **Roll back:** DigitalOcean → your app → **Activity** → pick a previous
  successful deploy → **Roll back**.
- **Rotate the Google key** (recommended, since it was shared in chat): Google
  Cloud → service account → Keys → delete old, create new JSON → update the
  `GOOGLE_SERVICE_ACCOUNT_JSON` env var in DigitalOcean → redeploy.
