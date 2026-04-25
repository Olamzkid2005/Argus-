#!/usr/bin/env python3
"""
Celery Worker Launcher

Simple wrapper to launch the Celery worker with proper Python environment.
"""
import os
import sys
import subprocess
import signal

# Get this script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Find the venv python
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python")
if not os.path.exists(VENV_PYTHON):
    # Fallback to system python
    VENV_PYTHON = sys.executable

CELERY_BIN = os.path.join(SCRIPT_DIR, "venv", "bin", "celery")

# Ensure we're in the workers directory
os.chdir(SCRIPT_DIR)

# Make sure the PROJECT_ROOT is at the start of sys.path
PROJECT_ROOT = SCRIPT_DIR
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def main():
    """Launch the Celery worker."""
    args = [
        VENV_PYTHON,
        CELERY_BIN,
        "-A", "celery_app",
        "worker",
        "--loglevel=info",
        "--concurrency=4",
        "-Q", "celery,recon,scan,analyze,report,repo_scan",
    ]
    
    print(f"Starting Celery worker with: {' '.join(args)}")
    print(f"Working directory: {os.getcwd()}")
    print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}")
    
    # Start the worker
    proc = subprocess.Popen(
        args,
        cwd=SCRIPT_DIR,
        env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
    )
    
    print(f"Celery worker started with PID: {proc.pid}")
    
    # Handle shutdown signals
    def handle_signal(signum, frame):
        print(f"Received signal {signum}, shutting down...")
        proc.terminate()
        proc.wait()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    # Wait for the worker to finish
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()