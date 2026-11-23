#!/usr/bin/env python3
"""
Fail CI when worker/agent code imports the dispatcher-owned graph surface.

C-18 says one dispatcher owns graph writes. ``database/graph_ownership.py``
enforces that at runtime; this script enforces the import boundary statically so
a new module cannot quietly bypass the dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

WORKERS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKERS_ROOT))

from database.graph_ownership import find_import_boundary_violations  # noqa: E402


def main() -> int:
    violations = find_import_boundary_violations(WORKERS_ROOT)
    if violations:
        print("C-18 violation: these modules import the dispatcher-owned graph surface directly:")
        for violation in violations:
            print(f"  - {violation}")
        print("Route graph writes through database.dispatcher_graph.DispatcherGraph instead.")
        return 1
    print("C-18 import boundary OK: no worker/agent module imports the graph write surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
