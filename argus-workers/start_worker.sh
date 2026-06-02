#!/bin/bash
# Start Celery worker with proper venv Python

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
CELERY_BIN="$SCRIPT_DIR/venv/bin/celery"

# Change to workers directory so PYTHONPATH is correct
cd "$SCRIPT_DIR"

# Execute celery with venv Python
exec "$VENV_PYTHON" "$CELERY_BIN" -A celery_app worker --loglevel=info --concurrency=4 -Q celery,recon,scan,analyze,report,repo_scan