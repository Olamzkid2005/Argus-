"""
Nuclei templates auto-update utility.

Keeps the local nuclei-templates directory fresh so new CVEs are detected.
Can be called:
- At scan start (gated by feature flag ARGUS_FF_NUCLEI_TEMPLATES_AUTO_UPDATE)
- As a daily Celery Beat task
"""
import logging
import os
import subprocess
from pathlib import Path

from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

NUCLEI_BINARY = "nuclei"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "tool_assets" / "nuclei-templates"


def update_nuclei_templates(timeout: int = 120) -> bool:
    """
    Run nuclei -update-templates to refresh the local template cache.

    Args:
        timeout: Maximum seconds to wait for the update (default 120)

    Returns:
        True if update succeeded, False otherwise
    """
    slog = ScanLogger("nuclei_updater")

    # Ensure templates directory exists
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [NUCLEI_BINARY, "-update-templates", "-update-directory", str(TEMPLATES_DIR)]
    slog.info(f"Updating nuclei templates: {' '.join(cmd)}")
    logger.info(f"Updating nuclei templates: {' '.join(cmd)}")

    try:
        env = os.environ.copy()
        env["HOME"] = str(Path.home())
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if result.returncode == 0:
            slog.info("Nuclei templates updated successfully")
            logger.info(
                f"Nuclei templates updated successfully. "
                f"stdout: {result.stdout[:500]}, stderr: {result.stderr[:500]}"
            )
            return True
        else:
            slog.warn(f"Nuclei templates update returned code {result.returncode}")
            logger.warning(
                f"Nuclei templates update returned code {result.returncode}. "
                f"stdout: {result.stdout[:500]}, stderr: {result.stderr[:500]}"
            )
            return False

    except subprocess.TimeoutExpired:
        slog.warn(f"Nuclei templates update timed out after {timeout}s")
        logger.error(f"Nuclei templates update timed out after {timeout}s")
        return False
    except FileNotFoundError:
        slog.warn(f"Nuclei binary '{NUCLEI_BINARY}' not found on PATH")
        logger.warning(
            f"Nuclei binary '{NUCLEI_BINARY}' not found on PATH. "
            f"Skipping template update."
        )
        return False
    except Exception as e:
        slog.warn(f"Nuclei templates update failed: {e}")
        logger.error(f"Nuclei templates update failed: {e}")
        return False


def get_template_count() -> int:
    """Count YAML templates in the local templates directory."""
    if not TEMPLATES_DIR.exists():
        return 0
    try:
        return sum(1 for _ in TEMPLATES_DIR.rglob("*.yaml"))
    except Exception:
        return 0
