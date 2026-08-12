# Operations Guide — Vasant Oasis Chatbot

Day-to-day operations for the deployed pilot. For first-time setup see
[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md). Paths below are relative to the
repository root, matching the post-cleanup layout (`/app`, `/deployment`,
`/docs`, `/data`).

## 1. Starting the server

```bash
cp .env.example .env   # first time only — fill in real keys/origins
docker compose up -d --build
curl http://localhost/health
```

To run the backend directly (no Docker, e.g. for local debugging):

```bash
cd app/inventory_system
python -X utf8 chat_api.py
```

Stop with `docker compose down` (data in `./data` and `./app/IVR_Sheet.xlsx`
persist via bind mounts).

## 2. Refreshing inventory

The inventory workbook is hot-swappable — no rebuild/restart needed:

1. Replace `app/IVR_Sheet.xlsx` with the updated workbook (same filename).
2. Trigger a reload:
   ```bash
   curl -X POST http://localhost/admin/refresh_inventory \
        -H "Authorization: Bearer $CHAT_ADMIN_API_KEYS"
   ```
3. Confirm via `GET /health` — `inventory_count` reflects the new sheet.

## 3. Media upload process

Media sync reads vehicle photos/videos and writes their URLs back into the
inventory workbook media columns, using `app/media_sync/media_sync_service.py`
(built on the validated primitives in `app/media_sync_poc/`).

1. Place new media under the vehicle's registration-number folder (see
   `Uploads/<REG_NO>/Exterior|Interior|Videos/`).
2. Run the sync service (see `app/media_sync/media_sync_service.py` /
   `media_audit.py` / `media_reconciliation.py` for audit and reconciliation
   passes).
3. Re-run `/admin/refresh_inventory` (step 2 above) so the chat API picks up
   the new media URLs.

## 4. Backup process

Daily backup of the SQLite databases and the inventory workbook:

```bash
./deployment/backup.sh         # writes to a timestamped archive (DATA_DIR=./data, XLSX=./app/IVR_Sheet.xlsx)
```

Restore:

```bash
./deployment/restore.sh <backup-archive>
```

Recommended cron (see `deployment/backup.sh` header):
```
0 2 * * * cd /opt/chatbot && ./deployment/backup.sh >> /var/log/chatbot-backup.log 2>&1
```

## 5. Pilot dashboard

```bash
python app/ops/pilot_dashboard.py --db data/pilot_query_log.db
```

Returns JSON with `total_conversations`, `total_messages`,
`inventory_success_pct`, `faq_success_pct`, `unknown_pct`,
`lead_capture_pct`, top unknown queries, and top languages. See
`docs/analytics_schema.md` for the underlying `query_log`/`unknown_log`
schema and `docs/monitoring_guide.md` for how it's wired up
(`InstrumentedChatService`, `app/inventory_system/chat_api.py`).

## 6. Daily review process

```bash
# 1. KPI snapshot (one row per day)
python app/ops/pilot_metrics.py --db data/pilot_query_log.db

# 2. Failure triage (categorizes every unresolved/unmatched turn)
python app/ops/pilot_triage.py --db data/pilot_query_log.db

# 3. Weekly management rollup
python app/ops/pilot_weekly_summary.py --db data/pilot_query_log.db
```

Watch against the baseline in `docs/pilot_operations_guide.md` /
`archive/reports/updated_kpi_baseline.md`:

| Metric | Baseline | Escalate if |
|---|---:|---|
| Inventory Success % | ~97% | drops below 90% |
| FAQ Success % | ~100% | drops below 95% |
| Unknown % | ~20% | rises above 25% |
| Lead Capture % | ~95-100% | drops below 80% |

## 7. Common troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` returns non-200 / container unhealthy | App crashed on startup, often a bad `IVR_Sheet.xlsx` or missing `.env` | `docker compose logs app`; verify `app/IVR_Sheet.xlsx` exists and opens in Excel; verify `.env` has required keys |
| `/chat` returns 401/403 | Missing/incorrect `CHAT_API_KEYS` header | Check client sends `Authorization: Bearer <key>` matching `.env` |
| `/chat` returns 429 | Rate limit hit (`CHAT_RATE_LIMIT`/`CHAT_RATE_WINDOW`) | Expected under abuse; raise limits in `.env` only if legitimate traffic |
| Inventory count not updating after workbook swap | Forgot to call `/admin/refresh_inventory`, or wrong admin key | Re-run step 2 above |
| `pilot_query_log.db` not growing | `chat_api.py` not wired to `InstrumentedChatService`, or wrong `pilot_log_db` path | Verify `app/inventory_system/chat_api.py` `run()` constructs `InstrumentedChatService(pilot_log_db="data/pilot_query_log.db")` (see `archive/reports/service_wiring_audit.md`) |
| Media URLs missing on a vehicle | Media not synced / workbook not refreshed | Re-run media sync (section 3) then `/admin/refresh_inventory` |
| Regression suite failures | 3 pre-existing, documented failures unrelated to deployment (status-enum rename + inventory count 44 vs 40 fixtures) | See `deployment_package_report.md` — not blockers |
