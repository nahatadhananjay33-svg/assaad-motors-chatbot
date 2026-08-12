# Phase 10A — System Architecture (as measured from the repository)

**Date:** 2026-07-30 · Research-only phase — no code was modified.
Every fact below was measured from the actual repo, not assumed.

## 1. Backend

| Aspect | Fact |
|---|---|
| Framework | **None — pure Python standard library.** `ThreadingHTTPServer` + `BaseHTTPRequestHandler` ([chat_api.py](app/inventory_system/chat_api.py)). No Flask/FastAPI/Django, no gunicorn/uvicorn needed. |
| Process model | Single process, one thread per request. One long-lived service object (inventory in memory). |
| Python | Developed on **3.14**; no version-specific features observed — **3.11+ safe** on the server. |
| LLM usage | **None in production.** The router accepts an optional `llm_client` but it is `None` by default — all routing/replies are deterministic. **Zero AI-API cost.** |
| Startup | Loads the Excel once (~1–2 s, 44 cars) then serves from memory. |

## 2. Runtime dependencies (only two)

```
openpyxl>=3.1   # Excel read/write
supabase>=2.0   # media storage SDK (falls back to in-memory demo store if env unset)
```
(+ their transitive deps: httpx etc. — installed footprint well under 200 MB.)

## 3. Data stores

| Store | Type | Size today | Purpose |
|---|---|---|---|
| `app/IVR_Sheet.xlsx` | Excel file | **140 KB** (95 cols × ~190 rows, 44 live cars) | **Single source of truth** for inventory. Written one row at a time (atomic save + `.lock` file + backup). |
| `data/pilot_query_log.db` | SQLite | 6.5 MB | Every customer query logged |
| `app/inventory_system/data/analytics.db` | SQLite | 11 MB | Chat analytics events |
| `app/inventory_system/data/leads.db` | SQLite | 5.6 MB | Lead capture |
| `unknown_queries.db`, `media_audit.db`, `media_journal.db` | SQLite | ~2 MB | Misc logs |
| `app/inventory_backups/` | Files | 5.3 MB | Auto Excel backups, pruned to keep ~20 |

Total application + data footprint today: **≈ 42 MB**. No external database server.

## 4. Media storage

- **Supabase Storage** (project `hxjxqdufquowvpmucqmf`, buckets `car-photos`, `car-videos`). Public URLs written into the Excel.
- Credentials come from env vars `SUPABASE_URL` / `SUPABASE_KEY` — **the app does NOT read `.env` itself**; if unset it silently falls back to a demo in-memory store (a known operational trap — see risks).
- Currently on the **free tier**, which **pauses the project after ~1 week of inactivity** (bit us during Phase 8J) and caps file storage at 1 GB / egress 5 GB/mo.
- YouTube/Instagram video **links** are stored in Excel (no storage cost).

## 5. Static files (no build step)

- `app/inventory_system/inventory_admin.html` — owner Inventory Dashboard (Phase 9C)
- `app/inventory_system/media_admin.html` — owner Media panel
- `app/website_widget/{demo.html, widget.js, widget.css}` — customer chat widget (embeddable via one script tag)

Plain HTML/JS; can be served by any web server (Nginx) or opened locally.

## 6. Background services

**None.** No queues, no workers, no cron jobs inside the app. (Deployment will add OS-level extras: backups, log rotation, and a Supabase keep-alive ping.)

## 7. API endpoints

| Public | Admin (X-API-Key, `/admin/*` fails closed) |
|---|---|
| `GET /health` | `POST /admin/refresh_inventory` · `GET /admin/inventory_status` · `POST /admin/upload_inventory` |
| `POST /chat` | `GET /admin/inventory/{dashboard,schema,vehicles}` · `POST /admin/inventory/{get_car,update_car,add_car,restore_car,duplicate_audit}` |
| | `GET /admin/media/vehicles` · `POST /admin/media/{upload_photos,upload_videos,add_link,mark_sold}` |

Security: admin key(s) via `CHAT_ADMIN_API_KEYS`; optional public API keys `CHAT_API_KEYS`; rate limiting (120 req/60 s default); CORS configurable (`ALLOWED_ORIGINS`); PII masking in logs.

## 8. Measured resource profile (basis for sizing)

| Metric | Measured value |
|---|---|
| RAM of fully-loaded service after chats | **≈ 49 MB RSS** |
| Chat latency (deterministic, in-memory) | ~0.4–0.5 s |
| Inventory load (44 cars) | ~1–2 s, one-time at start / on refresh |
| Admin dashboard read (full 95-col workbook) | ~0.9 s |
| Row write (edit/add) incl. atomic save + refresh | ~1.5 s (serialized by file lock) |
| Repo + data on disk | ~42 MB (+ Python runtime ~150 MB) |

**Implication:** this is one of the lightest possible production workloads — a 1 vCPU / 1 GB VPS is genuinely sufficient; 2 GB gives comfortable headroom.
