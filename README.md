# Vasant Oasis Chatbot — Production Repository

Deterministic (no-LLM, no-RAG) car-dealership chatbot backend: a parser → FAQ /
inventory-retrieval → response-formatter pipeline, with lead capture,
analytics/pilot instrumentation, media sync, and a website chat widget.

## Layout

```
/app                  production code
  inventory_system/   chat API, parser, retrieval, FAQ, leads, analytics,
                       pilot instrumentation (+ co-located tests)
  media_sync/          media-sync service (Supabase storage sync)
  media_sync_poc/      validated POC primitives reused by media_sync (runtime dep)
  ops/                 pilot dashboard/metrics/triage/weekly-summary tools
  website_widget/      embeddable chat widget (HTML/CSS/JS)
  IVR_Sheet.xlsx       inventory workbook (source of truth)

/deployment            nginx config, backup/restore scripts, monitoring checklist
/docs                  active operational/reference docs (monitoring, analytics
                       schema, frontend API contract, widget spec, pilot guides)
/data                  live pilot logs + generated KPI/triage outputs
/tests                 see tests/README.md (tests are co-located with code)
/archive               phase reports, evaluation datasets, one-off scripts
                       (not part of the production deployment)

Dockerfile, docker-compose.yml, .env.example, .gitignore   — root deployment config
DEPLOYMENT_GUIDE.md, OPERATIONS_GUIDE.md                    — start here
```

## Quick start

```bash
cp .env.example .env   # fill in real values
docker compose up -d --build
curl http://localhost/health
```

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for deployment details and
[OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) for day-to-day operations
(server start, inventory refresh, media uploads, backups, pilot dashboard).
