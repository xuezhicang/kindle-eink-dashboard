#!/usr/bin/env bash
# Collect Codex + Claude usage, draw the Kindle image, and upload it.
#
#   ./run.sh              full run (cron runs this every 10 minutes)
#   ./run.sh --no-upload  collect + draw only, nothing is uploaded
#
# Output goes to logs/run.log (and also to the terminal when run by hand).

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1

UPLOAD=1
[ "${1:-}" = "--no-upload" ] && UPLOAD=0

# cron starts with an almost empty environment, so set what we need here.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PY="$DIR/env/bin/python"

mkdir -p data logs
LOG="$DIR/logs/run.log"
# keep the log small: rotate at 1 MB, keep one old copy
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1048576 ]; then
    mv -f "$LOG" "$LOG.1"
fi
if [ -t 1 ]; then
    exec > >(tee -a "$LOG") 2>&1
else
    exec >>"$LOG" 2>&1
fi

# Only one run at a time. If the previous run is still going, skip this one.
exec 9>"$DIR/data/run.lock"
if ! flock -n 9; then
    echo "$(date '+%F %T') previous run still in progress, skipping"
    exit 0
fi

echo "=== $(date '+%F %T %Z') start"

# A failed collector keeps its last good data, so we still draw and upload.
for source in weather codex claude aerisiq; do
    "$PY" "read-$source.py"
done

if ! "$PY" generate.py; then
    echo "generate failed, not uploading (the old image stays on the Kindle)"
    exit 1
fi

if [ "$UPLOAD" = 0 ]; then
    echo "--no-upload: skipped upload"
    exit 0
fi

env_value() { sed -n "s/^$1=//p" .env | head -n 1 | tr -d '\r'; }
URL="$(env_value UPLOAD_URL)"
TOKEN="$(env_value UPLOAD_TOKEN)"
if [ -z "$URL" ] || [ -z "$TOKEN" ]; then
    echo "UPLOAD_URL or UPLOAD_TOKEN is missing in .env, not uploading"
    exit 1
fi
case "$TOKEN" in
    *\"* | *\\*) echo "UPLOAD_TOKEN must not contain quotes or backslashes"; exit 1 ;;
esac

# The token goes to curl through stdin (--config -), never on the command
# line: other users on this shared machine can see command lines with `ps`.
if printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
    curl --config - --fail-with-body --show-error --silent \
        --retry 3 --max-time 60 \
        -X PUT "$URL" \
        -H "Content-Type: image/png" \
        --data-binary "@dashboard.png"; then
    echo
    echo "upload ok"
else
    echo
    echo "upload FAILED"
    exit 1
fi
