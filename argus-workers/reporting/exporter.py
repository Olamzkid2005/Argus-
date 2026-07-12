"""
Report Export — file I/O at the application boundary.

Architecture (ADR-024):
    Rendering is pure (no I/O, no side effects) — see reporting/html_report.py.
    File writing lives exclusively in this module at the application boundary.
    Browser launching is a CLI-only concern handled by open_in_browser().

    All functions in this module perform file I/O or subprocess calls.
    They are NOT pure — they are the application boundary where side effects
    are explicitly allowed and concentrated.

Usage:
    from reporting.exporter import save_report

    # Save HTML report
    html = render_html_report(target="https://example.com", findings=[...])
    result = save_report(html, "report.html", fmt="html")

    # Save with auto-generated filename
    result = save_report(html, fmt="html", target_slug="example.com")
    # Writes to: reports/assessment-example-com-2026-06-09.html

    # Open in browser after saving
    result = save_report(html, "report.html", open_browser=True)
"""

import datetime
import logging
import os
import subprocess
import sys
import webbrowser

from tool_core._compat import utc
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ReportFormat = Literal["html", "markdown", "json"]

# Default output directory relative to CWD
DEFAULT_REPORT_DIR = "reports"


class ExportResult:
    """Result of a report export operation."""

    def __init__(
        self,
        path: str,
        fmt: ReportFormat,
        size_bytes: int,
        opened: bool = False,
    ):
        self.path = path
        self.fmt = fmt
        self.size_bytes = size_bytes
        self.opened = opened

    def __repr__(self) -> str:
        return (
            f"ExportResult(path={self.path!r}, fmt={self.fmt!r}, "
            f"size={self.size_bytes}, opened={self.opened})"
        )


def _ensure_report_dir(report_dir: str | Path) -> Path:
    """Create the report output directory if it doesn't exist.

    This is the ONLY function in the reporting package that creates
    directories — side effects are concentrated at the boundary.

    Args:
        report_dir: Path to the report output directory.

    Returns:
        Resolved Path to the directory.
    """
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _generate_filename(
    fmt: ReportFormat,
    target_slug: str | None = None,
    timestamp: datetime.datetime | None = None,
) -> str:
    """Generate a deterministic, ISO-ish filename for a report.

    Format: assessment-{target_slug}-{date}.{ext}

    Examples:
        assessment-example-com-2026-06-09.html
        assessment-example-com-2026-06-09.md
        assessment-example-com-2026-06-09.json

    Args:
        fmt: Report format extension.
        target_slug: URL-safe target identifier (domain or name).
        timestamp: Optional timestamp (defaults to now).

    Returns:
        Filename string (no directory prefix).
    """
    ts = timestamp or datetime.datetime.now(utc)
    date_str = ts.strftime("%Y-%m-%d")

    ext_map: dict[ReportFormat, str] = {
        "html": "html",
        "markdown": "md",
        "json": "json",
    }

    if target_slug:
        # Sanitize: lowercase, replace non-alphanumeric with hyphens, collapse
        slug = (
            target_slug.lower()
            .replace("https://", "")
            .replace("http://", "")
            .replace("/", "-")
            .replace(":", "")
            .replace(".", "-")
        )
        slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
        slug = "-".join(filter(None, slug.split("-")))
        return f"assessment-{slug}-{date_str}.{ext_map[fmt]}"

    return f"assessment-report-{date_str}.{ext_map[fmt]}"


def save_report(
    content: str,
    path: str | None = None,
    *,
    fmt: ReportFormat = "html",
    target_slug: str | None = None,
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    open_browser: bool = False,
) -> ExportResult:
    """Save a rendered report to disk.

    This is the primary file-I/O boundary for report exports.
    It handles:
    - Directory creation (if needed)
    - File path resolution
    - UTF-8 file writing
    - Optional browser launch

    Args:
        content: The rendered report content (HTML string, Markdown, or JSON).
        path: Explicit output path. If None, generates a deterministic filename
              using target_slug and fmt.
        fmt: Report format — "html", "markdown", or "json".
        target_slug: URL-safe target identifier for auto-generated filenames.
        report_dir: Output directory (default: "reports/" relative to CWD).
        open_browser: If True, open the saved file in the default browser.
                      Only supported for HTML format.

    Returns:
        ExportResult with path, format, size, and opened status.

    Raises:
        ValueError: If open_browser is True for non-HTML formats.
        IOError: If the file cannot be written.
    """
    if open_browser and fmt != "html":
        raise ValueError(
            f"open_browser is only supported for HTML reports, got '{fmt}'"
        )

    out_dir = _ensure_report_dir(report_dir)

    if path:
        out_path = Path(path)
        # If path is relative, resolve relative to report_dir
        if not out_path.is_absolute():
            out_path = out_dir / out_path
    else:
        filename = _generate_filename(fmt, target_slug=target_slug)
        out_path = out_dir / filename

    # Ensure parent directory exists (in case path includes subdirectories)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    try:
        out_path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise OSError(f"Failed to write report to {out_path}: {e}") from e

    size_bytes = out_path.stat().st_size
    opened = False

    logger.info(
        "Report saved: %s (%s, %d bytes)",
        out_path,
        fmt.upper(),
        size_bytes,
    )

    if open_browser:
        _open_in_browser(out_path)
        opened = True

    return ExportResult(
        path=str(out_path.resolve()),
        fmt=fmt,
        size_bytes=size_bytes,
        opened=opened,
    )


def open_in_browser(path: str | Path) -> None:
    """Open a report file in the default browser.

    This is a convenience wrapper for CLI usage.
    It delegates to save_report() with open_browser=True or can be called
    directly with an already-saved file path.

    This is the ONLY function in the reporting package that launches a
    browser — side effects are concentrated at the CLI boundary.

    Args:
        path: Path to the report file to open.

    Raises:
        FileNotFoundError: If the report file does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Report file not found: {p.resolve()}")

    _open_in_browser(p)


def _open_in_browser(path: Path) -> None:
    """Internal helper to open a file in the browser.

    Uses webbrowser.open() on all platforms.
    Falls back to platform-specific commands if webbrowser fails.
    """
    uri = path.resolve().as_uri()

    try:
        if webbrowser.open(uri):
            logger.info("Opened report in browser: %s", uri)
            return
    except Exception:
        logger.debug("webbrowser.open() failed, trying platform fallbacks")

    # Platform fallbacks
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True, timeout=10)
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(path)], check=True, timeout=10)
        elif sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            logger.warning("No browser opener known for platform: %s", sys.platform)
            return
        logger.info("Opened report via platform opener: %s", path)
    except Exception as e:
        logger.warning("Failed to open report in browser: %s", e)
