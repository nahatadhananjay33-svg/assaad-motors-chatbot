#!/usr/bin/env bash
# Restore the chatbot stores from a backup archive produced by backup.sh.
# STOP the app first so files are not being written during restore.
#
#   docker compose stop app
#   ./deploy/restore.sh ./backups/chatbot-backup-YYYYMMDD-HHMMSS.tar.gz
#   docker compose start app
set -euo pipefail

ARCHIVE="${1:?usage: restore.sh <backup.tar.gz>}"
DATA_DIR="${DATA_DIR:-./data}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

tar -xzf "$ARCHIVE" -C "$STAGE"
mkdir -p "$DATA_DIR"

for name in leads analytics unknown_queries; do
    if [ -f "$STAGE/${name}.db" ]; then
        cp "$STAGE/${name}.db" "$DATA_DIR/${name}.db"
        echo "restored ${name}.db"
    fi
done

echo "restore complete from: $ARCHIVE"
echo "NOTE: restore IVR_Sheet.xlsx manually if needed (it is in the archive)."
