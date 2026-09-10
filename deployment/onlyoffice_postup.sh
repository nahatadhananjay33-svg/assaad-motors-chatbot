#!/usr/bin/env bash
# Run AFTER `docker compose up -d`. ONLYOFFICE regenerates local.json on every
# container start, so re-apply the request-filtering-agent override that lets it
# reach our app on the private docker network (the app has a private IP), then
# restart the doc-server's internal services. Idempotent; safe to run any time.
set -euo pipefail

C=$(docker ps -qf "name=assad-motors-onlyoffice" | head -1)
if [ -z "$C" ]; then echo "onlyoffice container not found"; exit 1; fi

echo "waiting for ONLYOFFICE healthcheck..."
for i in $(seq 1 60); do
  r=$(docker exec "$C" curl -s http://localhost/healthcheck 2>/dev/null || true)
  if [ "$r" = "true" ]; then echo "healthy after $((i*3))s"; break; fi
  sleep 3
done

docker exec --user root "$C" python3 - <<'PY'
import json
p = "/etc/onlyoffice/documentserver/local.json"
c = json.loads(open(p).read())
c.setdefault("services", {}).setdefault("CoAuthoring", {})["request-filtering-agent"] = {
    "allowPrivateIPAddress": True, "allowMetaIPAddress": True}
open(p, "w").write(json.dumps(c, indent=2))
print("allowPrivateIPAddress enabled in local.json")
PY

docker exec "$C" supervisorctl restart all >/dev/null 2>&1 || true
echo "onlyoffice reconfigured + services restarted"
