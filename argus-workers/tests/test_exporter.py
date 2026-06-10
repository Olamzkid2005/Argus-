"""
Tests for reporting/exporter.py — file I/O at the application boundary.

Verifies:
- save_report() writes files to disk correctly
- Auto-generated filenames match expected format
- Directory creation works
- Browser opening is called (or raises for non-HTML)
- Error handling for missing files
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from reporting.exporter import (
    ExportResult,
    _ensure_report_dir,
    _generate_filename,
    open_in_browser,
    save_report,
)


class TestGenerateFilename:
    """Tests for _generate_filename() — deterministic file naming."""

    def test_html_format(self):
        """HTML format produces .html extension."""
        name = _generate_filename("html", target_slug="example.com")
        assert name.endswith(".html")
        assert "assessment-example-com" in name

    def test_markdown_format(self):
        """Markdown format produces .md extension."""
        name = _generate_filename("markdown", target_slug="example.com")
        assert name.endswith(".md")
        assert "assessment-example-com" in name

    def test_json_format(self):
        """JSON format produces .json extension."""
        name = _generate_filename("json", target_slug="example.com")
        assert name.endswith(".json")
        assert "assessment-example-com" in name

    def test_no_target_slug(self):
        """Without target_slug, uses generic name."""
        name = _generate_filename("html")
        assert name.startswith("assessment-report-")
        assert name.endswith(".html")

    def test_url_sanitization(self):
        """URL-like strings are sanitized to safe slugs."""
        name = _generate_filename("html", target_slug="https://example.com/api/v1")
        assert "https://" not in name
        assert name.endswith(".html")

    def test_date_included(self):
        """Filename includes the current date."""
        import datetime
        today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        name = _generate_filename("html", target_slug="test")
        assert today in name


class TestEnsureReportDir:
    """Tests for _ensure_report_dir() — directory creation."""

    def test_creates_directory(self, tmp_path):
        """Directory is created if it doesn't exist."""
        test_dir = tmp_path / "reports" / "nested"
        result = _ensure_report_dir(test_dir)
        assert test_dir.exists()
        assert test_dir.is_dir()
        assert result == test_dir.resolve()

    def test_existing_directory(self, tmp_path):
        """Existing directory is returned unchanged."""
        test_dir = tmp_path / "existing"
        test_dir.mkdir(parents=True)
        result = _ensure_report_dir(test_dir)
        assert test_dir.exists()
        assert result == test_dir.resolve()


class TestSaveReport:
    """Tests for save_report() — the primary export function."""

    def test_saves_html_file(self, tmp_path):
        """save_report writes HTML content to disk."""
        content = "<html><body><h1>Test</h1></body></html>"
        result = save_report(content, "test.html", report_dir=tmp_path)
        saved = tmp_path / "test.html"
        assert saved.exists()
        assert saved.read_text(encoding="utf-8") == content
        assert result.path.endswith("test.html")
        assert result.fmt == "html"

    def test_saves_markdown_file(self, tmp_path):
        """save_report writes Markdown content to disk."""
        content = "# Test Report\n\nFindings: 5"
        result = save_report(content, "test.md", fmt="markdown", report_dir=tmp_path)
        saved = tmp_path / "test.md"
        assert saved.exists()
        assert saved.read_text(encoding="utf-8") == content
        assert result.fmt == "markdown"

    def test_saves_json_file(self, tmp_path):
        """save_report writes JSON content to disk."""
        content = '{"findings": 5, "severity": "high"}'
        result = save_report(content, "test.json", fmt="json", report_dir=tmp_path)
        saved = tmp_path / "test.json"
        assert saved.exists()
        assert saved.read_text(encoding="utf-8") == content
        assert result.fmt == "json"

    def test_auto_generated_filename(self, tmp_path):
        """Without explicit path, generates filename from target_slug."""
        content = "<html>Report</html>"
        result = save_report(content, fmt="html", target_slug="example.com", report_dir=tmp_path)
        # Should have auto-generated name with target slug
        assert "example" in result.path
        assert result.path.endswith(".html")

    def test_default_report_dir(self, tmp_path):
        """Uses DEFAULT_REPORT_DIR when no report_dir is specified."""
        content = "<html>Report</html>"
        # Patch os.getcwd to return our tmp_path
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = save_report(content, fmt="html", target_slug="test")
            assert "reports" in result.path

    def test_file_size_reported(self, tmp_path):
        """ExportResult includes correct file size."""
        content = "Hello, World!" * 100
        result = save_report(content, "size_test.html", report_dir=tmp_path)
        assert result.size_bytes > 0
        saved = tmp_path / "size_test.html"
        assert result.size_bytes == saved.stat().st_size

    def test_nested_path_creates_parent(self, tmp_path):
        """save_report creates parent directories in the path."""
        content = "<html>Report</html>"
        result = save_report(content, "nested/deep/report.html", report_dir=tmp_path)
        saved = tmp_path / "nested" / "deep" / "report.html"
        assert saved.exists()
        assert result.path.endswith("report.html")

    def test_open_browser_html(self, tmp_path):
        """open_browser=True opens HTML in browser."""
        content = "<html></html>"
        with patch("reporting.exporter._open_in_browser") as mock_open:
            result = save_report(content, "browser.html", report_dir=tmp_path, open_browser=True)
            mock_open.assert_called_once()
            assert result.opened is True

    def test_open_browser_non_html_raises(self, tmp_path):
        """open_browser=True for non-HTML raises ValueError."""
        content = "# Markdown"
        with pytest.raises(ValueError, match="open_browser is only supported for HTML"):
            save_report(content, "test.md", fmt="markdown", report_dir=tmp_path, open_browser=True)

    def test_io_error_writes_exception(self, tmp_path):
        """Permission error or disk full raises IOError."""
        content = "<html></html>"
        with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
            with pytest.raises(IOError, match="Failed to write report"):
                save_report(content, "fail.html", report_dir=tmp_path)


class TestOpenInBrowser:
    """Tests for open_in_browser() — browser launch."""

    def test_missing_file_raises(self):
        """Opening a non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Report file not found"):
            open_in_browser("/nonexistent/report.html")

    def test_existing_file_opens(self, tmp_path):
        """Opening an existing file calls _open_in_browser."""
        report = tmp_path / "report.html"
        report.write_text("<html></html>")
        with patch("reporting.exporter._open_in_browser") as mock_open:
            open_in_browser(report)
            mock_open.assert_called_once()

    def test_export_result_string(self):
        """ExportResult repr includes all fields."""
        result = ExportResult(path="/tmp/report.html", fmt="html", size_bytes=1024, opened=True)
        r = repr(result)
        assert "report.html" in r
        assert "html" in r
        assert "1024" in r
        assert "True" in r
