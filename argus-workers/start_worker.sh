#!/bin/bash
# Start Celery worker with proper venv Python

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

# Use venv celery if available, fall back to system PATH
if [ -f "$SCRIPT_DIR/venv/bin/celery" ]; then
  CELERY_BIN="$SCRIPT_DIR/venv/bin/celery"
else
  CELERY_BIN="celery"
fi

# Change to workers directory so PYTHONPATH is correct
cd "$SCRIPT_DIR"

# Pre-flight: warn loudly when external tool binaries are missing. Non-fatal —
# the worker still starts, but the operator sees exactly what to install
# instead of discovering silent fallback at scan time.
if [ -f "$SCRIPT_DIR/scripts/install_tools.py" ]; then
  "$VENV_PYTHON" "$SCRIPT_DIR/scripts/install_tools.py" --check || echo "[start_worker] WARNING: some tools are missing — run: python scripts/install_tools.py"
fi

# Execute celery with venv Python
exec "$VENV_PYTHON" "$CELERY_BIN" -A celery_app worker --loglevel=info --concurrency=4 -Q celery,recon,scan,analyze,report,repo_scan