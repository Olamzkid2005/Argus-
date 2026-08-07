"""Argus CLI package."""

import sys
from pathlib import Path

# Ensure project root is on path (same as original cli.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .cmd.assess import cmd_assess
from .cmd.health import cmd_health
from .cmd.init import cmd_init
from .cmd.list import cmd_list
from .cmd.report import cmd_report
from .cmd.resume import cmd_resume
from .cmd.scan import cmd_scan
from .cmd.trends import cmd_trends
from .cmd.verify import cmd_verify
from .main import build_parser, main

__all__ = [
    "main",
    "build_parser",
    "cmd_assess",
    "cmd_scan",
    "cmd_report",
    "cmd_list",
    "cmd_health",
    "cmd_resume",
    "cmd_trends",
    "cmd_verify",
    "cmd_init",
]
