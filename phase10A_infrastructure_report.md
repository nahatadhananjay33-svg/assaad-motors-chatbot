# Phase 10A — Production Infrastructure Report & Cost Optimization

**Date:** 2026-07-30 · Research-only — nothing was purchased, provisioned, or changed in code.
Companion doc: [phase10A_system_architecture.md](phase10A_system_architecture.md) (measured system facts).

---

## 1. Resource requirements (from measurements, not guesses)

Measured base: service RSS ≈ 49 MB; chat ≈ 0.5 s CPU-light; Excel 140 KB; all SQLite ≈ 25 MB; media lives in Supabase (not on the VPS); chat responses are a few KB of JSON (photos are served by Supabase, not your server).

| Profile | Assumptions | vCPU | RAM | Disk | Bandwidth |
|---|---|---|---|---|---|
| **Small dealership** (today) | ≤100 cars, 1–3 staff, ~200 chats/day, ~5 concurrent users peak | **1** | **1 GB** (app ~80 MB + OS ~300 MB + headroom) | **10 GB** | < 5 GB/mo |
| **Medium** | ≤500 cars, 5–10 staff, 1–2k chats/day, ~25 concurrent | **2** | **2 GB** | **20 GB** | ~20 GB/mo |
| **Large** | 2,000+ cars, 20+ staff, 10k chats/day, ~100 concurrent | 2–4 | 4 GB | 40 GB | ~50 GB/mo (+ DB migration — see §9) |

Assumptions explained: each chat request is deterministic string/dict work (~0.5 s of one core, no GPU, no LLM API). Concurrency = threads; 1 vCPU comfortably sustains ~2 req/s continuous (≈ 170k chats/day) — customer chat traffic will never be the bottleneck before inventory size is. Storage growth is dominated by SQLite logs (~25 MB per few months of pilot use → budget 1–2 GB/yr) and Excel backups (capped by pruning).

---

## 2. VPS provider comparison (researched July 2026)

Prices are entry/low-tier monthly, rounded; promotional vs renewal noted where known.

| Provider | Cheapest useful plan | ~Price/mo | India DC | India latency | Scaling | Notes |
|---|---|---|---|---|---|---|
| **Vultr** | 1 vCPU / 1 GB / 25 GB NVMe | **$5–6** (plans from $2.50 IPv6-only) | ✅ **Mumbai, Delhi, Bangalore** | ~1–5 ms in-city | Resize in place, hourly billing | Best India coverage; backups +20% (~$1.20) |
| **DigitalOcean** | Basic Droplet 1 GB | $6 ($4 for 512 MB) | ✅ Bangalore (BLR1) | ~10–25 ms from Mumbai | Excellent (snapshots, resize, monitoring) | Most polished tooling/docs; backups +20% |
| **Linode / Akamai** | Nanode 1 GB | $5 | ✅ Mumbai | ~1–5 ms | Good | Solid reputation; backups +$2 |
| **Hostinger** | KVM 2: 2 vCPU / **8 GB** / 100 GB | **$7–10 promo** (24-mo term; renewal higher) | ✅ India | low | Panel-based | Huge specs for the price, weekly backups included, INR billing & support; long lock-in for best price |
| **OVHcloud** | VPS from $4.20–6.50 | $4–7 | ✅ Mumbai | low | OK | Bandwidth quota in APAC (500 GB then throttled — fine for us); panel less friendly |
| **Hetzner** | CX22 2 vCPU / 4 GB / 40 GB | ~€4.35 (+June 2026 price rises; Singapore location costs more) | ❌ (Singapore closest) | ~50–70 ms | Excellent | Best raw value in EU, but no India DC and recent price increases |
| **Contabo** | Cloud VPS 4 vCPU / 8 GB | $5.30–8 | ❌ (Singapore/Japan) | ~50–90 ms | OK | Big specs, cheap; known over-provisioning → variable performance; slower support |
| **Oracle Cloud Free** | Ampere ARM (free tier **cut June 2026 to 2 OCPU / 12 GB**) | **$0** | ✅ Mumbai region | low | N/A | Idle instances can be **reclaimed**; account/setup friction; fine for a staging box, **not for the production dealership system** |

**India latency matters here** because customers chat from Mumbai and staff use the dashboard from the showroom. 50–70 ms (Singapore) is still usable for this app (responses are ~0.5 s anyway), but an India DC removes the concern entirely for the same money.

---

## 3. Recommendations (Step 4)

- 🥉 **Best budget:** **Vultr — Cloud Compute, Mumbai, 1 vCPU / 1 GB / 25 GB, ~$6/mo** (+$1.20 auto-backups). Cheapest serious option physically in Mumbai; hourly billing, easy resize when you grow.
- 🥈 **Best value-for-money:** **Hostinger KVM 2, India, ~$7–10/mo** — 8 GB RAM / 100 GB NVMe is ~8× the resources for ~1.5× the price, weekly backups included, INR billing and Hindi-capable support (nice for the dealership's non-technical owner). Trade-off: best price needs a 24-month commitment and renewal is higher.
- 🥇 **Best long-term production:** **DigitalOcean Basic Droplet, Bangalore, 1 GB → 2 GB ($6 → $12) + backups (+20%)**. Not the absolute cheapest, but the most mature tooling (one-click resize, snapshots, monitoring/alerts, firewalls, docs), highest operational predictability, and 10–25 ms latency is irrelevant for a 0.5 s chatbot. When the dealership's business depends on uptime, boring reliability wins.

**Overall pick for this project now: Vultr Mumbai $6/mo (1 GB) with auto-backups (~$7.20 total).** The app measured at 49 MB RAM — paying for 8 GB would be waste today; Vultr lets you resize to 2 GB/2 vCPU in minutes when Phase 9C dashboards get heavier use. If the owner prefers a friendlier panel + bundled backups + INR billing over flexibility, Hostinger KVM 2 is the alternative.

**Not just the cheapest:** Oracle's $0 tier was rejected for production (reclaim risk + June 2026 downgrade), and Contabo's cheap large specs were rejected for variable performance and no India DC.

---

## 4. Recommended server specification (Step 5)

| Item | Minimum production spec | Why |
|---|---|---|
| CPU | 1 vCPU (2 nice-to-have) | Chat uses ~0.5 s of one core; admin ops ~1.5 s |
| RAM | **1 GB** (2 GB comfortable) | Service ≈ 49 MB; Nginx ≈ 10 MB; OS ≈ 300 MB |
| Disk | 25 GB NVMe | App+data ≈ 42 MB; logs/backups grow slowly |
| OS | **Ubuntu 24.04 LTS** | Boring, documented, 5-yr support |
| Python | **3.12** from Ubuntu repos (app needs 3.11+) | No exotic features used |
| Swap | 1–2 GB swapfile | Safety net on a 1 GB box |
| Backups | Provider auto-backup ON + nightly script (Excel + SQLite → off-server) | Excel is the single source of truth — two independent backup paths |
| Firewall | UFW: allow 22, 80, 443 only | Port 8000 must NOT be public — app sits behind Nginx |
| SSL | **Let's Encrypt (free)** via certbot (or Caddy) | Zero cost, auto-renewing |

---

## 5. Production deployment architecture (Step 6)

```
                Internet (customers + staff)
                        │ HTTPS 443
                ┌───────▼────────┐   optional: Cloudflare free tier in front
                │     Nginx      │   TLS (Let's Encrypt), serves the static files
                │ reverse proxy  │   (widget.js/css, admin HTMLs), gzip, rate limit,
                └───────┬────────┘   proxies /chat + /admin/* to 127.0.0.1:8000
                        │
                ┌───────▼────────────────┐
                │  chat_api.py (systemd) │  env: CHAT_ENV=production, CHAT_ADMIN_API_KEYS,
                │  ThreadingHTTPServer   │  CHAT_API_KEYS?, ALLOWED_ORIGINS,
                │  bound to 127.0.0.1    │  SUPABASE_URL, SUPABASE_KEY
                └──┬─────────────┬───────┘
                   │             │
        ┌──────────▼───┐   ┌────▼──────────────┐
        │ IVR_Sheet.xlsx│   │ Supabase Storage  │  car-photos / car-videos buckets
        │ + SQLite DBs  │   │ (public URLs)     │  + daily keep-alive ping (cron)
        │ on local disk │   └───────────────────┘
        └──────┬────────┘
               │ logrotate (JSON logs) 
        ┌──────▼─────────────────────────┐
        │ Nightly backup (cron):         │
        │ Excel + *.db → tar.gz →        │
        │ provider backup + off-server   │
        └────────────────────────────────┘
```

**Every component explained:**
- **Nginx** — the only thing exposed to the internet. Terminates HTTPS, serves the 5 static files directly, forwards API calls to the app on localhost, adds a second rate-limit layer. (The stdlib Python server is fine behind a proxy; it should never face the internet directly.)
- **systemd service** — starts the app at boot, restarts on crash, injects the env vars (fixes the "started without Supabase keys → silent demo mode" trap permanently).
- **Excel + SQLite on local disk** — unchanged; the app's own locking/atomic-save already handles concurrent staff writes.
- **Supabase Storage** — unchanged media workflow. A **daily keep-alive cron** (e.g. `curl` a storage URL / tiny select) prevents the free-tier 1-week pause that broke Phase 8J testing.
- **Backups** — two independent layers: provider snapshot/auto-backup + nightly tar of Excel+DBs pushed off-server (even a private Supabase bucket or emailed archive works at this size — the whole dataset is ~50 MB).

---

## 6. Production security checklist (Step 7)

- [ ] **HTTPS** on 443 via Let's Encrypt, auto-renew (`certbot renew` timer); HTTP→HTTPS redirect
- [ ] **Firewall (UFW):** default deny; allow 22/80/443; app bound to 127.0.0.1:8000 only
- [ ] **SSH:** key-only login (`PasswordAuthentication no`), no root login, non-standard port optional
- [ ] **Fail2Ban** on sshd (and optionally on Nginx 4xx floods) — appropriate here
- [ ] **Environment variables** in the systemd unit (`Environment=` / `EnvironmentFile=` with 600 perms) — never in code or repo
- [ ] **API keys:** strong random `CHAT_ADMIN_API_KEYS` (not `testadmin`!); set `CHAT_ENV=production`; set `ALLOWED_ORIGINS` to the real site origin (removes the CORS `*` warning); consider `CHAT_API_KEYS` if the widget will be key-gated
- [ ] **Supabase:** keep the service key server-side only; keep-alive cron; buckets stay public-read only (no service key in any client page)
- [ ] **Automatic backups:** provider backups ON + nightly Excel/SQLite archive off-server + periodic restore TEST
- [ ] **Log rotation:** logrotate for app JSON logs + Nginx logs (size/time based)
- [ ] **Monitoring:** UptimeRobot (free) hitting `/health` every 5 min with email/WhatsApp alert; provider CPU/disk alerts
- [ ] **Automatic security updates:** `unattended-upgrades` for Ubuntu security patches
- [ ] **App hardening already present** (verified in Phase 8J): admin auth fails closed, rate limiting, PII masking — just needs production env values

---

## 7. Monthly cost estimate (Step 8)

| Item | Minimum setup | Recommended setup |
|---|---|---|
| VPS | Vultr Mumbai 1 GB — **$6.00** | Vultr 1 GB + auto-backups — **$7.20** (or Hostinger KVM 2 ≈ $9) |
| Domain (.com/.in, yearly ÷ 12) | ~$1.00 | ~$1.00 |
| SSL | $0 (Let's Encrypt) | $0 |
| Supabase | $0 (free tier + keep-alive) | $0 now → **$25 Pro later if media outgrows 1 GB / 5 GB egress** |
| Off-server backup storage | $0 (fits in free tiers) | $0–1 |
| Monitoring | $0 (UptimeRobot free) | $0 |
| **Total** | **≈ $7/mo (~₹600)** | **≈ $8–10/mo (~₹700–850)** |
| Future scaling (500+ cars, heavy media) | | ≈ **$14 VPS (2 GB) + $25 Supabase Pro ≈ $39/mo (~₹3,300)** |

**Biggest cost lever:** Supabase Pro ($25) costs 3–4× the VPS. Two free mitigations: (a) keep-alive cron avoids paying just to prevent pausing; (b) prefer **YouTube/Instagram links for videos** (already fully supported by the app) and keep only photos in Supabase — photos for even 200 cars (~20 × 300 KB × 200 ≈ 1.2 GB) only slightly exceed the free tier, and image compression on upload could keep it under.

---

## 8. Future scalability (Step 9)

| Scale | What happens | Action needed |
|---|---|---|
| **100 cars** | Excel ~300 KB; load ~2–4 s; dashboard ~1 s | **Nothing changes.** |
| **500 cars** | Excel ~1.5 MB; startup/refresh ~5–10 s; row-save ~2–3 s; dashboard ~2–4 s | Still fine. Consider 2 GB / 2 vCPU ($12). Supabase Pro likely needed for photos. |
| **2,000 cars** | Excel ~6 MB; every save rewrites the whole file (~10 s); dashboard reads slow; openpyxl memory grows | Works, but admin UX degrades. Add caching for dashboard reads; start planning DB migration. |
| **10,000 cars** | Excel becomes the bottleneck: multi-minute loads, single-writer lock contention, fragile file | **Migrate inventory to SQLite/Postgres** (keep Excel as an export/report format). Chatbot & retrieval logic stay the same — only the loader changes. |
| **10 staff** | Writes serialize on the existing file lock (~1.5 s each) | Fine as-is. |
| **50 staff** | Lock contention → queued saves, "Excel is open" style friction | Same DB migration solves it (row-level DB writes). |

**What can stay the same forever:** the chatbot logic, retrieval, media workflow, admin UI, security layer, and the one-VPS architecture (a 4 GB VPS handles all realistic chat traffic). **What eventually changes:** only the storage layer under the loader — Excel → database — a contained change the current code structure (single `inventory_loader.py`) makes straightforward.

---

## 9. Risks

1. **Supabase free-tier pause** (bit us in Phase 8J) — mitigated by keep-alive cron; eliminated by Pro when revenue justifies.
2. **Silent demo-mode fallback** if Supabase env vars are missing at start — mitigated permanently by systemd `EnvironmentFile`; worth a future one-line "refuse to start in production without creds" check (not in this phase).
3. **Silent media-upload failures** — `media_admin.py` swallows upload errors and still reports "✓ uploaded" (found in Phase 8J). Operational risk on flaky networks; candidate for a small later fix.
4. **Excel as DB at large scale** — see scalability table; not a today-problem.
5. **Single-server design** — an outage takes chat down until restart (systemd auto-restart + UptimeRobot alert keeps this to minutes). Acceptable at this budget; a second server/HA is not justified.
6. **Promo pricing lock-ins** (Hostinger 24-mo) and **renewal jumps** — read renewal price before committing.
7. **Duplicate CAR NUMB rows in Excel** (MH02EZ6001 found by Phase 9C audit) — data hygiene, fix in Excel when convenient.

---

## 10. Final recommendation & deployment roadmap (Step 10)

**Buy:** Vultr **Cloud Compute — Mumbai**, 1 vCPU / 1 GB / 25 GB NVMe (~$6/mo) **+ auto-backups** (~$1.20). Total **≈ $7.20/mo (~₹620)**, resize-in-place path to 2 GB/$12 when needed. *(Alternative if the owner wants a friendlier panel + INR billing: Hostinger KVM 2 India ≈ $9/mo on a 24-month term.)*

**Roadmap (for the future deployment phase — not executed now):**
1. Buy VPS (Ubuntu 24.04) + domain; point DNS.
2. Harden: UFW, SSH keys, Fail2Ban, unattended-upgrades, swapfile.
3. Install Python 3.12 + `pip install -r requirements.txt`; copy the app + Excel.
4. Create systemd unit with all env vars (`CHAT_ENV=production`, real admin key, `ALLOWED_ORIGINS`, Supabase creds).
5. Nginx: TLS (certbot), static files, reverse proxy to 127.0.0.1:8000, rate limit.
6. Cron: nightly Excel+SQLite backup off-server; daily Supabase keep-alive.
7. UptimeRobot on `/health`; provider alerts on CPU/disk.
8. Re-run the Phase 8J smoke tests against the live URL before pointing the real widget at it.

**Expected outcome achieved:** provider chosen (Vultr Mumbai), config chosen (1 GB → 2 GB path), monthly cost known (≈ $7 now, ≈ $39 at full scale), safe-deploy checklist written, and a clear scale path where only the Excel storage layer ever needs replacing.

---

*Pricing sources (July 2026):*
[Hetzner CX22 pricing](https://vpsfor.dev/posts/hetzner-cx22-pricing-2026/) · [Hetzner 2026 price increases](https://northflank.com/blog/hetzner-cloud-server-price-increases) · [Hostinger KVM2 review](https://stackcapybara.com/tools/hostinger-kvm2/) · [Cheap VPS India 2026](https://aiccloud.in/blog/top-10-cheap-vps-hosting-india-2026) · [Vultr/Linode/DO comparison](https://valebyte.com/en/blog/vultr-vs-linode-vs-digitalocean-which-cloud-vps-to-choose-in-2026/) · [Contabo pricing](https://cybernews.com/best-web-hosting/contabo-review/pricing/) · [Oracle free tier 2026 changes](https://space-node.net/blog/oracle-vps-free-tier-review-2026) · [OVH India VPS](https://www.ovhcloud.com/en/vps/vps-india/) · [Supabase pricing 2026](https://uibakery.io/blog/supabase-pricing) · [Supabase free-tier pauses](https://www.itpathsolutions.com/supabase-free-tier-limits)
