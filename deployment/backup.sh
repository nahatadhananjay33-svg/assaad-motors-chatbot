#!/usr/bin/env bash
# Consistent backup of the chatbot SQLite stores + inventory workbook.
#
# Uses SQLite's online ".backup" so it is safe while the app is running
# (no need to stop the container). Produces a timestamped .tar.gz and prunes
# old archives.
#
# Run on the HOST (data is bind-mounted to ./data). Requires: sqlite3, tar.
#   sudo apt-get install -y sqlite3
#
# Cron (daily 02:00):
#   0 2 * * * cd /opt/chatbot && ./deployment/backup.sh >> /var/log/chatbot-backup.log 2>&1
set -euo pipefail

DATA_DIR="${DATA_DIR:-./data}"
XLSX="${XLSX:-./app/IVR_Sheet.xlsx}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

TS="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$BACKUP_DIR"

for name in leads analytics unknown_queries; do
    src="$DATA_DIR/${name}.db"
    if [ -f "$src" ]; then
        # online, crash-consistent copy (works with WAL too)
        sqlite3 "$src" ".backup '$STAGE/${name}.db'"
    else
        echo "warn: $src not found (skipping)" >&2
    fi
done

# include the source-of-truth workbook
[ -f "$XLSX" ] && cp "$XLSX" "$STAGE/IVR_Sheet.xlsx" || echo "warn: $XLSX not found" >&2

ARCHIVE="$BACKUP_DIR/chatbot-backup-$TS.tar.gz"
tar -czf "$ARCHIVE" -C "$STAGE" .
echo "backup written: $ARCHIVE"

# retention
find "$BACKUP_DIR" -name 'chatbot-backup-*.tar.gz' -mtime +"$RETAIN_DAYS" -delete
echo "pruned archives older than ${RETAIN_DAYS} days"

# OPTIONAL off-site copy (uncomment + configure):
#   aws s3 cp "$ARCHIVE" "s3://your-bucket/chatbot-backups/"
#   rclone copy "$ARCHIVE" remote:chatbot-backups/
