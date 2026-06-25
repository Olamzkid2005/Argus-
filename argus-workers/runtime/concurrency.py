"""
Global concurrency management for tool execution.

Provides semaphores that gate subprocess execution at the tool_runner level,
preventing unbounded concurrent subprocesses across Celery workers.

Usage in tool_runner.py:
    from runtime.concurrency import SUBPROCESS_SEMAPHORE, HIGH_COST_SEMAPHORE
    with SUBPROCESS_SEMAPHORE:
        result = subprocess.run(...)
"""

import threading
from config.constants import MAX_CONCURRENT_REQUESTS

# Global semaphore limiting total concurrent subprocesses across all tools.
# The default of 20 prevents runaway subprocess creation while allowing
# reasonable parallelism for typical multi-phase assessments.
SUBPROCESS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

# Stricter semaphore for high-cost / destructive tools (sqlmap, masscan, etc.)
# Capped at roughly 1/3 of the general limit.
HIGH_COST_TOOLS = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}
HIGH_COST_SEMAPHORE = threading.BoundedSemaphore(
    max(1, MAX_CONCURRENT_REQUESTS // 3)
)
