# Assad Motors — Deploy to Hostinger KVM2 (Docker)

Chatbot public • Owner/staff panel behind login • Docker + nginx • Supabase for media.

Two phases on purpose:
- **Phase 1 — HTTP on the server IP.** Prove the app + panel + chatbot work end-to-end. Fast, no domain needed.
- **Phase 2 — Domain + HTTPS + production lockdown.** Do this before real staff/customer use (login over plain HTTP is insecure).

Everything below runs on the **server over SSH** unless it says "(on your PC)".

---

## 0. Before you start — have these ready
- KVM2 **server IP** + root/SSH password (Hostinger hPanel → VPS → Overview).
- (Phase 2) A **domain or subdomain** you can point at that IP. Hostinger KVM plans often include one.
- Your **Supabase** URL + keys (from your local `.env`, or Supabase dashboard → Project Settings → API).
- Keep Supabase **awake** (free tier sleeps after ~1 week idle → media breaks). Paid tier or the keep-alive task.

---

## 1. Prepare the server (Ubuntu)
SSH in (on your PC, PowerShell): `ssh root@YOUR_SERVER_IP`

```bash
apt update && apt -y upgrade
# Firewall: allow SSH + web only
apt -y install ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
# Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

---

## 2. Get the project onto the server
The clean way (excludes Windows/dev junk — do NOT upload `cloudflared.exe`, `*.log`, `__pycache__`, `tests/`, `phase*.md`).

**Option A — rsync (on your PC, from Git Bash / WSL):**
```bash
rsync -av --delete \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='*.log' --exclude='tests/' --exclude='cloudflared.exe' \
  --exclude='*.md' --exclude='Uploads/' --exclude='.env' \
  "/c/Users/ASUS/Desktop/Assad_Papa_Mumbai_work/Assad_Bhaiya_work/" \
  root@YOUR_SERVER_IP:/opt/assad/
```
**Option B — ask me to build a clean `.zip`**, upload it in Hostinger's File Manager, then on the server: `cd /opt && unzip assad_deploy.zip -d assad`.

Then: `cd /opt/assad`

---

## 3. Configure secrets (`.env`)
```bash
cp .env.production.example .env
# generate strong keys:
echo "admin: $(openssl rand -hex 24)"; echo "chat: $(openssl rand -hex 24)"
nano .env
```
Fill in: `CHAT_ADMIN_API_KEYS`, `CHAT_API_KEYS`, the **Supabase** vars, and `ALLOWED_ORIGINS`.
- **Phase 1 (IP test):** set `CHAT_ENV=development` for now (lets you use the raw IP without CORS/cert errors).
- **Phase 2:** set `CHAT_ENV=production` and `ALLOWED_ORIGINS=https://yourdomain.com`.

---

## 4. Web root + inventory file
nginx serves the pages; the app reads the Excel from the writable `data/` volume.
```bash
# static pages nginx will serve (customer chatbot + panel)
# Copy the JS/CSS too — not just the HTML. index.html loads style.css/app.js/
# config.js, and EVERY panel page loads auth_guard.js (it provides AUTH.base, so
# without it the panel dies with "Connect first" and no inventory ever loads).
mkdir -p deployment/web/inventory_system
cp app/chat_app/index.html            deployment/web/index.html
cp app/chat_app/app.js                deployment/web/
cp app/chat_app/style.css             deployment/web/
cp app/chat_app/config.js             deployment/web/
cp app/inventory_system/*.html        deployment/web/inventory_system/
cp app/inventory_system/auth_guard.js deployment/web/inventory_system/

# Point the chat page at the SAME ORIGIN. The shipped default is the dev value
# (host:8000), which cannot work in production: 8000 is firewalled and plain HTTP.
# nginx proxies /chat, so an empty apiUrl is correct.
sed -i 's#^  apiUrl:.*#  apiUrl: ""   // same origin — nginx proxies /chat#' deployment/web/config.js

# seed the inventory workbook into the writable data dir
mkdir -p data
# upload your corrected Excel to the server first, then:
cp Assad_Motors_CORRECTED_12-8-26.xlsx data/IVR_Sheet.xlsx
```
Panel login page will be: `http://YOUR_SERVER_IP/inventory_system/login.html`
Customer chatbot: `http://YOUR_SERVER_IP/`

> **Developer Dashboard (read-only monitoring):** the `*.html` copy above already
> includes `developer_dashboard.html`. To enable the developer login, set BOTH
> `DEV_DASHBOARD_USER` and `DEV_DASHBOARD_PASSWORD` in `.env` (env-required — if
> unset, there is no developer account and the dashboard cannot be entered).
> After launch it is reachable at `http://YOUR_SERVER_IP/developer` (or the
> pretty URL `https://yourdomain.com/developer` in Phase 2). Only the Developer
> account can open it; staff, and even the Owner, are rejected.

---

## 5. Phase 1 — launch on HTTP and verify
`docker-compose.yml` already points nginx at `nginx.http.conf` (HTTP). Start it:
```bash
docker compose up -d --build
docker compose ps
curl -s http://localhost/health          # -> {"status":"ok","inventory_count":...}
```
In a browser: open `http://YOUR_SERVER_IP/inventory_system/login.html`, log in (owner), confirm the inventory list, upload/edit works, and the customer chatbot answers at `http://YOUR_SERVER_IP/`.
Logs if anything's off: `docker compose logs -f app` / `docker compose logs -f nginx`.

---

## 6. Phase 2 — domain + HTTPS + lockdown
1. Point your domain's **A record** → `YOUR_SERVER_IP` (wait for DNS to propagate).
2. Get a certificate (webroot method):
```bash
mkdir -p deployment/certs deployment/certbot-webroot
apt -y install certbot
certbot certonly --webroot -w /opt/assad/deployment/certbot-webroot \
  -d yourdomain.com --email you@example.com --agree-tos --no-eff-email
cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem deployment/certs/
cp /etc/letsencrypt/live/yourdomain.com/privkey.pem   deployment/certs/
```
3. Switch nginx to the HTTPS config: in `docker-compose.yml`, change the nginx line
   `./deployment/nginx.http.conf` → `./deployment/nginx.conf`, and set your domain as `server_name` in `deployment/nginx.conf`.
4. In `.env` set `CHAT_ENV=production` and `ALLOWED_ORIGINS=https://yourdomain.com`.
5. Reload: `docker compose up -d`  (app refuses to start if production settings are insecure — fix what it prints).
6. Verify `https://yourdomain.com/health` and the login page over HTTPS.
7. Cert auto-renew (cron, monthly): re-copy certs to `deployment/certs/` and `docker compose exec nginx nginx -s reload`.

---

## 7. Backups & monitoring
- **Nightly backup** (cron): backs up `data/` (Excel + all SQLite). `deployment/backup.sh` is here; schedule with `crontab -e`:
  `15 2 * * * cd /opt/assad && ./deployment/backup.sh`
- The panel also auto-backs up the Excel on every upload (`data/inventory_backups/`, last 20 kept).
- **Supabase keep-alive** so media URLs keep working (paid tier is simplest).
- Uptime check hitting `/health`. See `deployment/MONITORING_CHECKLIST.md`.

---

## 8. Day-2: update / restart
```bash
cd /opt/assad
git pull            # or re-run the rsync from your PC
docker compose up -d --build        # rebuild + restart with zero data loss (data/ persists)
docker compose logs -f app
```
Inventory changes don't need any of this — the owner uploads a new Excel in the panel and it hot-reloads.

---

## Notes / gotchas
- The Excel lives in `data/IVR_Sheet.xlsx` (writable) so the panel can edit it; do **not** revert it to a read-only mount.
- Don't publish source: nginx already 404s `*.py/*.db/*.log/*.xlsx` and `/data/`.
- `CHAT_ENV=production` is a safety gate — it will refuse to boot without an admin key, an explicit CORS list, and a positive rate limit.
