# Monitoring Checklist — Pilot (100–500 conversations/day)

The backend emits one JSON log line per event (stdout → `docker compose logs app`)
and persists data to `./data/*.db`. No dashboard required for the pilot — these
checks are runnable from the shell. Watch these five signals daily.

> Log event names: `service_init, chat, http_access, request_denied,
> bad_request, leak_blocked, unhandled_error, inventory_refresh, refresh_error,
> server_start, server_stop`.

---

## 1. Response time
- **Source:** `http_access` log lines, field `ms` (per request); `chat` lines, field `latency_ms`.
- **Check:**
  ```bash
  docker compose logs --since 1h app | grep '"event": "http_access"' \
    | python -c "import sys,json; xs=[json.loads(l.split(' ',0)[0] if False else l[l.find('{'):])['ms'] for l in sys.stdin if '{' in l]; xs.sort(); print('n=%d p50=%.1f p95=%.1f max=%.1f'%(len(xs),xs[len(xs)//2],xs[int(len(xs)*0.95)],xs[-1]))" 2>/dev/null
  ```
- **Healthy:** p95 < 50 ms (deterministic, in-memory retrieval). **Alert:** p95 > 500 ms.

## 2. Error rate
- **Source:** `http_access` status codes; `unhandled_error`, `refresh_error` events.
- **Check:**
  ```bash
  docker compose logs --since 1h app | grep -c '"status": 5'      # 5xx count
  docker compose logs --since 1h app | grep -c '"event": "unhandled_error"'
  ```
- **Healthy:** 0 unhandled errors; 5xx ≈ 0. **Alert:** any sustained 5xx, or `leak_blocked` > 0 (a privacy backstop fired — investigate immediately).
- Also watch `request_denied` (401/429): a spike of 401 = wrong/missing keys; 429 = rate limit hits.

## 3. Lead volume
- **Source:** `data/leads.db`.
- **Check:**
  ```bash
  sqlite3 data/leads.db "SELECT score_level, COUNT(*) FROM leads GROUP BY score_level;"
  sqlite3 data/leads.db "SELECT COUNT(*) FROM leads WHERE visit_ready=1;"   # visit-ready
  sqlite3 data/leads.db "SELECT COUNT(*) FROM leads WHERE phone IS NOT NULL;" # with contact
  ```
- **Watch:** High/Medium counts and visit-ready trend. A pilot is converting if visit-ready leads accumulate daily.

## 4. Unknown queries
- **Source:** `data/unknown_queries.db` (the FAQ/LLM backlog).
- **Check:**
  ```bash
  sqlite3 data/unknown_queries.db "SELECT COUNT(*) FROM unknown_queries;"
  sqlite3 data/unknown_queries.db \
    "SELECT LOWER(TRIM(query)) q, COUNT(*) n FROM unknown_queries GROUP BY q ORDER BY n DESC LIMIT 15;"
  sqlite3 data/unknown_queries.db "SELECT language, COUNT(*) FROM unknown_queries GROUP BY language;"
  ```
- **Action:** if `unknown` share is high or a cluster repeats (e.g. "best family car"), promote it to a deterministic FAQ (Phase 3B) or scope it for the future LLM. Target: keep unknown < 10%.

## 5. Inventory refresh status
- **Source:** `inventory_refresh` / `refresh_error` events; `/health` `inventory_count`.
- **Check:**
  ```bash
  curl -s https://yourdomain.com/health | python -m json.tool   # inventory_count, coverage
  docker compose logs --since 24h app | grep '"event": "inventory_refresh"' | tail -1
  ```
- **Healthy:** a successful `inventory_refresh` after each morning file swap, with a sane `inventory_count`. **Alert:** `refresh_error`, or a stale `inventory_count` (no refresh logged today).

---

## Daily 2-minute routine
1. `curl /health` → status ok + inventory_count looks right.
2. `docker compose ps` → both services healthy; container HEALTHCHECK green.
3. Error/denied counts in the last 24h ≈ 0 (no 5xx, no `leak_blocked`).
4. Lead funnel counts (leads.db) trending up; note visit-ready.
5. Skim top unknown queries → log FAQ candidates.
6. Confirm last night's backup archive exists in `./backups/`.

## Weekly
- Pull `summary` numbers (route %, top vehicles, language split) by querying
  `analytics.db` (or via a short script using `AnalyticsEngine.summary_report`).
- Rotate/verify a backup restore on a scratch copy.
- Review unknown clusters → decide FAQ expansions for the next iteration.

## Alert thresholds (suggested)
| Signal | Warn | Page |
|---|---|---|
| 5xx errors / hour | ≥ 1 | ≥ 5 |
| `leak_blocked` | any | any |
| p95 latency | > 200 ms | > 1 s |
| `/health` failing | 1 check | 3 consecutive |
| No backup in 24h | — | yes |
| Unknown-query share | > 10% | > 25% |
