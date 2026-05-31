#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/john/code/OpenPaw"
VENV_DIR="/Users/john/Library/Caches/pypoetry/virtualenvs/openpaw-Eiw6AgHk-py3.13"
LOG_DIR="$HOME/logs/openpaw"

mkdir -p "$LOG_DIR"

PIDFILE="$LOG_DIR/openpaw.pid"

# Prevent duplicate instances
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "ERROR: OpenPaw is already running (PID $(cat "$PIDFILE")). Stop it first or remove $PIDFILE." >&2
    exit 1
fi

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/openpaw_${TIMESTAMP}.log"

# Symlink for convenience
ln -sf "$LOG_FILE" "$LOG_DIR/latest.log"

cd "$PROJECT_DIR"

# Load project .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Activate venv
source "$VENV_DIR/bin/activate"

echo "Starting OpenPaw at $(date)" | tee "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "---" | tee -a "$LOG_FILE"

# Write PID file and clean up on exit
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

# Run all workspaces, tee output to both terminal and log
python -m openpaw.cli -c config.yaml --all 2>&1 | tee -a "$LOG_FILE"
