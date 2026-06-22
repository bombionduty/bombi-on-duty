# Deploy Bombi On Duty on your existing Droplet (100% free)

Runs alongside your other bot. Free HTTPS via Caddy + Let's Encrypt on a
`nip.io` hostname — no domain, no monthly cost beyond the Droplet you already pay
for.

---

## Step 0 — Open a terminal on your Droplet (no SSH setup needed)
1. DigitalOcean → **Droplets** → click your Droplet.
2. Top-right → **Console** (or **Access → Launch Droplet Console**).
3. A black terminal opens in your browser, logged in as `root`.

## Step 1 — Check the Droplet (paste this, send Claude the output)
```bash
free -m; echo ---; (docker --version || echo "docker NOT installed"); echo ---; \
hostname -I; echo ---; ss -tlnp | grep -E ':80|:443' || echo "ports 80/443 are FREE"
```
- If ports 80/443 are **in use** by your other bot, tell Claude — we'll use a
  different setup so nothing breaks.

## Step 2 — Get the code
```bash
cd /opt 2>/dev/null || cd /root
git clone https://github.com/bombionduty/bombi-on-duty.git
cd bombi-on-duty
```
(If the repo is private, Git asks for your username + the GitHub token.)

## Step 3 — Create the .env (Claude gives you the full block to paste)
Claude will hand you one `cat > .env <<'EOF' ... EOF` block containing all your
secrets. Paste it in the console and press Enter. That writes the `.env` file.

## Step 4 — Deploy
```bash
bash scripts/deploy_droplet.sh
```
This auto-detects your IP, builds the nip.io HTTPS address, installs Docker if
needed, adds swap if RAM is low, and starts everything. Takes ~3–5 minutes the
first time (it builds the image).

When it finishes it prints your URL, e.g. `https://164-92-5-10.nip.io`.

## Step 5 — Verify
Open `https://YOUR-NIPIO-URL/healthz` in a browser → should show
`{"status":"ok"}`. The bot auto-registers its Telegram webhook on startup.

## Step 6 — Register the Mini App (BotFather, one time)
1. Telegram → **@BotFather** → `/newapp` → pick **@bombi_ondutybot**.
2. Title: `Bombi On Duty`  ·  Description: `Daily checklists.`  ·  upload any photo.
3. **Web App URL:** `https://YOUR-NIPIO-URL/static/staff/index.html`
4. **Short name:** `ops`

Done — the group "Open Checklist" button and the private "Admin Controls" button
now open the real Mini Apps.

---

## Everyday operations
- **View logs:** `docker compose -f deploy/docker-compose.yml logs -f app`
- **Restart:** `docker compose -f deploy/docker-compose.yml restart`
- **Update after a code change:** `git pull && docker compose -f deploy/docker-compose.yml up -d --build`
- **Stop:** `docker compose -f deploy/docker-compose.yml down`

## Notes / honest caveats
- The HTTPS address contains your Droplet's IP. If the IP changes, the URL
  changes (and you'd re-do BotFather Step 6). Lock it with a **free Reserved IP**
  in DigitalOcean → Networking → Reserved IPs.
- `nip.io` is a free public DNS helper. It's widely used and reliable; if it ever
  has issues, `sslip.io` works the same way as a drop-in replacement.
