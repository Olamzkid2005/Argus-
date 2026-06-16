"""
Tests for update_nuclei_templates module.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.update_nuclei_templates import get_template_count, update_nuclei_templates


class TestUpdateNucleiTemplates:
    """Tests for update_nuclei_templates()."""

    @pytest.fixture(autouse=True)
    def _mock_subprocess(self, request):
        with patch("tools.update_nuclei_templates.subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            request.cls._mock_run = mock
            yield

    @pytest.fixture(autouse=True)
    def _mock_templates_dir(self):
        with patch("tools.update_nuclei_templates.TEMPLATES_DIR"):
            yield

    def test_returns_true_on_success(self):
        result = update_nuclei_templates()

        assert result is True
        self._mock_run.assert_called_once()

    def test_returns_false_on_nonzero_exit(self):
        self._mock_run.return_value.returncode = 1

        result = update_nuclei_templates()

        assert result is False

    def test_returns_false_on_timeout(self):
        self._mock_run.side_effect = subprocess.TimeoutExpired(cmd="nuclei", timeout=120)

        result = update_nuclei_templates()

        assert result is False

    def test_returns_false_on_file_not_found(self):
        self._mock_run.side_effect = FileNotFoundError()

        result = update_nuclei_templates()

        assert result is False

    def test_returns_false_on_generic_exception(self):
        self._mock_run.side_effect = RuntimeError("unexpected failure")

        result = update_nuclei_templates()

        assert result is False

    def test_uses_restricted_environment(self):
        update_nuclei_templates()

        call_env = self._mock_run.call_args[1].get("env", {})
        assert "PATH" in call_env
        assert "HOME" in call_env
        assert "API_KEY" not in call_env
        assert "SECRET" not in call_env
        assert "TOKEN" not in call_env
        assert "PASSWORD" not in call_env


class TestGetTemplateCount:
    """Tests for get_template_count()."""

    def test_returns_zero_when_directory_does_not_exist(self):
        nonexistent = Path("/nonexistent/path")
        with patch("tools.update_nuclei_templates.TEMPLATES_DIR", nonexistent):
            count = get_template_count()

        assert count == 0

    def test_counts_yaml_files(self, tmp_path):
        template_dir = tmp_path / "nuclei-templates"
        template_dir.mkdir()
        (template_dir / "cve-2024-0001.yaml").touch()
        (template_dir / "cve-2024-0002.yaml").touch()
        sub = template_dir / "subdir"
        sub.mkdir()
        (sub / "cve-2024-0003.yaml").touch()
        (template_dir / "README.md").touch()
        (template_dir / "config.json").touch()

        with patch("tools.update_nuclei_templates.TEMPLATES_DIR", template_dir):
            count = get_template_count()

        assert count == 3
