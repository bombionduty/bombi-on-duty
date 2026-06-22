# Production Launch Checklist

Tick every box before the first real shift. Maps to the required test cases in
the specification (§48).

## A. Configuration
- [ ] `.env` (or Render env vars) filled in; `service_account.json` present or
      `GOOGLE_SERVICE_ACCOUNT_JSON` set.
- [ ] `TEST_MODE=false`, `ENVIRONMENT_NAME=production`, `TELEGRAM_MODE=webhook`.
- [ ] `SECRET_KEY` is a fresh random 64-hex string.
- [ ] `APP_BASE_URL` is the live HTTPS URL, no trailing slash.

## B. Google
- [ ] Sheet shared with service account as Editor.
- [ ] Drive evidence folder shared with service account as Editor.
- [ ] `python -m scripts.setup_sheet` ran — all tabs exist.
- [ ] `python -m scripts.seed_templates` ran — checklists + timing + settings seeded.

## C. Telegram
- [ ] Bot created; token set.
- [ ] Mini App short name `ops` created; Web App URL points at
      `/static/staff/index.html`.
- [ ] Bot is an **admin** of the Staff Daily Ops group; Topics OFF.
- [ ] `STAFF_GROUP_CHAT_ID` correct; `getWebhookInfo` shows no errors.

## D. People
- [ ] All real staff added in Staff tab with correct numeric Telegram IDs, Active.
- [ ] Each staff has pressed **/start** privately (so escalation DMs can reach
      them) — check "Private Bot Started" in Admin → Staff.
- [ ] Store OIC assigned (Admin → Staff → Make Store OIC). Angel by default.
- [ ] No duplicate active Telegram IDs warning.

## E. Schedule
- [ ] Today and the coming week have opener + closer (Admin → Schedule).
- [ ] Closed days marked CLOSED.

## F. Smoke tests (do these live, in a quiet window)
- [ ] 1–3. Bot starts; admin authenticates; a non-admin is rejected from admin pages.
- [ ] 6–8. `/test opening|handover|closing` (or wait for release) posts each card once.
- [ ] 9–10. Assigned staff opens the Mini App; a different staff is rejected.
- [ ] 11–14. Live camera works on iPhone + Android; gallery fallback works;
      screenshot upload works.
- [ ] 15–18. Required proof cannot be skipped; all-complete works; issue report
      works; a second submit is blocked.
- [ ] 19. Re-uploading the same image flags **Possible Duplicate** privately.
- [ ] 20–22. Reminder lists only missing items; OIC escalation sends once;
      cutoff marks **Not Submitted** with missing items recorded.
- [ ] 23–24. Assigned staff submits after cutoff → Completed Late; original
      cutoff event preserved.
- [ ] 25–31. OIC opens recovery, sees only missing items, uploads proof, reason
      required, original assignee + Not Submitted preserved, resolution becomes
      **Recovered by Store OIC**.
- [ ] 32. Weekly report counts the employee as missed (not on-time).
- [ ] 33–37. Daily summary shows **View All Evidence**; it opens the right date;
      **Send Evidence Here** delivers images privately with uploader/role captions;
      OIC recovery evidence is labelled.
- [ ] 38–39. `/note` works; announcement acknowledgements work (no duplicates).
- [ ] 40–42. Closed day skips tasks; missing opener/closer alerts the admin.
- [ ] 43. A checklist change applies to **future** tasks only.
- [ ] 44–45. Daily summary is accurate; a recovery updates the historical summary.
- [ ] 46–48. Restart creates no duplicates; slow upload recovers; Drive errors
      are handled gracefully.

## G. Go-live
- [ ] Keep-alive pinger configured (free plan) or starter plan enabled.
- [ ] Brief staff: "tap the button, fill the form, submit." Nothing to install.
- [ ] Watch the first full day; review the first daily summary.

## H. Rollback
- [ ] To pause: in @BotFather you can't delete instantly, but you can stop the
      Render service (no cards/reminders will post). Re-deploy to resume.
- [ ] Data is in Google Sheets/Drive — nothing is lost by stopping the service.
- [ ] To revert code: redeploy the previous Git commit on Render.
