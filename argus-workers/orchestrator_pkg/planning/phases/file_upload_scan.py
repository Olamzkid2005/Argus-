"""Phase: file_upload_scan — _activate_file_upload and _file_upload_scan_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: File Upload Testing ─────────────────────────────────────────


def _activate_file_upload(rc) -> tuple[bool, str]:
    """Activate when file upload functionality is detected."""
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload functionality detected"
    return False, "no file upload detected"


def _file_upload_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for file upload abuse testing."""
    return [
        ToolTask(
            tool_name="nuclei",
            description="File upload vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "file-upload,upload"],
        ),
    ]
