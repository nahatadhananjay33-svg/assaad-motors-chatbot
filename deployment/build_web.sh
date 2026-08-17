#!/usr/bin/env bash
# Build the nginx web root (deployment/web) from source.
#
# deployment/web/ is a DEPLOY ARTIFACT, not tracked in git (see .gitignore). It
# is regenerated from app/chat_app/ + app/inventory_system/ on every deploy, so
# the source tree stays the single source of truth and a wiped/again-empty web
# root self-heals on the next deploy. Run from the repo root (the deploy does:
# `git pull && bash deployment/build_web.sh && docker compose up -d --build app`).
#
# The only customisation over a raw copy: config.js apiUrl is forced to "" so the
# browser talks to the SAME ORIGIN (nginx proxies /chat); the shipped source
# value points at the dev host:8000 which cannot work in production.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root

WEB=deployment/web
mkdir -p "$WEB/inventory_system"

# customer chatbot (index + assets)
cp app/chat_app/index.html "$WEB/index.html"
cp app/chat_app/app.js     "$WEB/"
cp app/chat_app/style.css  "$WEB/"
cp app/chat_app/config.js  "$WEB/"

# owner / developer / media / inventory panels + the shared auth guard
cp app/inventory_system/*.html        "$WEB/inventory_system/"
cp app/inventory_system/auth_guard.js "$WEB/inventory_system/"

# same-origin API (nginx proxies /chat) — never the dev host:8000
sed -i 's#^  apiUrl:.*#  apiUrl: ""   // same origin — nginx proxies /chat#' "$WEB/config.js"

echo "web root built at $WEB:"
ls "$WEB" && echo "  inventory_system/:" && ls "$WEB/inventory_system"
