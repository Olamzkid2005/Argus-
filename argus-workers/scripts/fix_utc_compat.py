#!/usr/bin/env python3
"""
Fix ``datetime.UTC`` references for Python 3.10 compatibility.

Usage: python3 scripts/fix_utc_compat.py
"""

import os
import re

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_FILES = {
    "tool_core/_compat.py",
    "tool_core/result.py",
    "tool_core/base.py",
    "tools/cloud_metadata_probe.py",
    "scripts/fix_utc_compat.py",
}

# Files that already have the compat import but still use UTC
ALREADY_FIXED = {
    "tool_core/result.py",
    "tool_core/base.py",
    "tools/cloud_metadata_probe.py",
}

# Import rewrite patterns: (search_regex, replacement_lines)
IMPORT_FIXES = [
    # from datetime import UTC, datetime, timedelta
    ("from datetime import UTC, datetime, timedelta",
     ["from datetime import datetime, timedelta",
      "from tool_core._compat import utc"]),
    # from datetime import datetime, timedelta, UTC
    ("from datetime import datetime, timedelta, UTC",
     ["from datetime import datetime, timedelta",
      "from tool_core._compat import utc"]),
    # from datetime import UTC, datetime, timedelta
    ("from datetime import UTC, datetime, timedelta",
     ["from datetime import datetime, timedelta",
      "from tool_core._compat import utc"]),
    # from datetime import UTC, datetime
    ("from datetime import UTC, datetime",
     ["from datetime import datetime",
      "from tool_core._compat import utc"]),
    # from datetime import datetime, UTC
    ("from datetime import datetime, UTC",
     ["from datetime import datetime",
      "from tool_core._compat import utc"]),
    # from datetime import UTC (standalone)
    ("from datetime import UTC\n",
     ["from tool_core._compat import utc\n"]),
]


def fix_file(filepath: str) -> bool:
    with open(filepath) as f:
        content = f.read()

    relpath = os.path.relpath(filepath, PROJECT_DIR)
    if relpath in SKIP_FILES or relpath in ALREADY_FIXED:
        return False

    original = content

    # Check if datetime.UTC or datetime.now(UTC) is used
    if "UTC" not in content:
        return False
    if "tool_core._compat" in content:
        return False

    modified = False

    # Fix import statements
    for pattern, replacement_lines in IMPORT_FIXES:
        if pattern in content:
            indent = ""
            # Preserve indentation for inside-function imports
            for line in content.split("\n"):
                if pattern in line:
                    indent = line[:len(line) - len(line.lstrip())]
                    break
            fixed = "\n".join(indent + l for l in replacement_lines)
            content = content.replace(pattern, fixed)
            modified = True
            break  # Only match one import pattern

    if not modified:
        return False

    # Fix usage patterns
    # datetime.now(UTC) -> datetime.now(utc)
    if "datetime.now(UTC)" in content:
        content = content.replace("datetime.now(UTC)", "datetime.now(utc)")
    # datetime.datetime.now(datetime.UTC) -> datetime.datetime.now(utc)
    if "datetime.UTC" in content:
        content = content.replace("datetime.UTC", "utc")

    if content != original:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"  Fixed: {relpath}")
        return True

    return False


def main():
    count = 0
    for root, dirs, files in os.walk(os.path.join(PROJECT_DIR, "argus-workers")):
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "__pycache__")]
        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            if fix_file(filepath):
                count += 1

    print(f"\nFixed {count} file(s)")


if __name__ == "__main__":
    main()
