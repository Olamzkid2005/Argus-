import pytest
import re
from unittest.mock import patch, MagicMock
from tasks.repo_scan import (
    SECRET_PATTERNS,
    _extract_file_path,
    _check_patch_for_secrets,
    scan_git_history_for_secrets,
    scan_repo
)

# Test secret pattern matching
class TestSecretPatterns:
    def test_aws_access_key(self):
        pattern = SECRET_PATTERNS['aws_access_key']
        assert re.search(pattern, 'AKIAIOSFODNN7EXAMPLE')
        assert not re.search(pattern, 'AKIA123')  # Too short
    
    def test_github_token(self):
        pattern = SECRET_PATTERNS['github_token']
        assert re.search(pattern, 'ghp_abcdefghijklmnopqrstuvwxyz1234567890ABCD')
        assert not re.search(pattern, 'ghp_short')
    
    def test_private_key(self):
        pattern = SECRET_PATTERNS['private_key']
        assert re.search(pattern, '-----BEGIN RSA PRIVATE KEY-----')
        assert re.search(pattern, '-----BEGIN EC PRIVATE KEY-----')

# Test _extract_file_path
class TestExtractFilePath:
    def test_extract_from_added_file(self):
        lines = [
            'diff --git a/foo.py b/foo.py',
            '--- /dev/null',
            '+++ b/foo.py',
            '+hello world'
        ]
        assert _extract_file_path(lines, 4) == 'foo.py'
    
    def test_extract_from_modified_file(self):
        lines = [
            'diff --git a/bar.py b/bar.py',
            '--- a/bar.py',
            '+++ b/bar.py',
            'print("test")'
        ]
        assert _extract_file_path(lines, 4) == 'bar.py'
    
    def test_unknown_file(self):
        lines = ['no headers here']
        assert _extract_file_path(lines, 1) == 'unknown'

# Test _check_patch_for_secrets
class TestCheckPatchForSecrets:
    def test_find_secret_in_patch(self):
        findings = []
        patch_lines = [
            '+++ b/config.py',
            'api_key="abcdefghijklmnopqrstuvwxyz1234567890"'
        ]
        _check_patch_for_secrets(
            patch_lines, 'abc123', 'Alice', '2026-04-24', '/repo', findings
        )
        assert len(findings) == 1
        assert findings[0]['type'] == 'COMMITTED_SECRET'
        assert 'api_key' in findings[0]['title'].lower()
    
    def test_no_secrets_in_patch(self):
        findings = []
        patch_lines = ['+++ b/main.py', 'print("hello")']
        _check_patch_for_secrets(
            patch_lines, 'def456', 'Bob', '2026-04-23', '/repo', findings
        )
        assert len(findings) == 0

# Test git log parsing and scan_git_history_for_secrets
class TestGitHistoryScan:
    @patch('tasks.repo_scan.subprocess.run')
    def test_scan_with_secrets(self, mock_run):
        # Mock git log output with a secret
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='COMMIT:abc123|AUTHOR:Alice|DATE:2026-04-24\n'
                  '+++ b/secrets.py\n'
                  'api_key="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        findings = scan_git_history_for_secrets('/repo')
        assert len(findings) == 1
        assert findings[0]['commit_hash'] == 'abc123'
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_scan_git_log_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr='Not a git repository'
        )
        findings = scan_git_history_for_secrets('/repo')
        assert len(findings) == 0
    
    @patch('tasks.repo_scan.scan_git_history_for_secrets')
    def test_scan_repo_integration(self, mock_secret_scan):
        mock_secret_scan.return_value = [{'type': 'COMMITTED_SECRET'}]
        results = scan_repo('/repo')
        assert 'git_secret_findings' in results
        assert len(results['git_secret_findings']) == 1
