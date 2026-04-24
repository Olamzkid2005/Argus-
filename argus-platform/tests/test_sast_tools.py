import json
import pytest
from unittest.mock import patch, MagicMock
from tasks.repo_scan import (
    run_bandit,
    run_eslint_security,
    run_gosec,
    _detect_languages,
    _map_bandit_severity,
    _map_eslint_severity
)


class TestBanditOutputParsing:
    """Test Bandit output parsing."""
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_bandit_success(self, mock_run):
        bandit_output = {
            'results': [
                {
                    'issue_text': 'Possible hardcoded password',
                    'severity': 'HIGH',
                    'filename': '/test/app.py',
                    'line_number': 10,
                    'code': 'password = "secret123"',
                    'cwe': 'CWE-259',
                    'confidence': 'high'
                }
            ]
        }
        
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(bandit_output),
            stderr=''
        )
        
        findings = run_bandit('/test/repo')
        
        assert len(findings) == 1
        assert findings[0]['type'] == 'STATIC_ANALYSIS_FINDING'
        assert findings[0]['severity'] == 'HIGH'
        assert findings[0]['title'] == 'Possible hardcoded password'
        assert findings[0]['tool'] == 'bandit'
        assert findings[0]['cwe'] == 'CWE-259'
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_bandit_no_issues(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({'results': []}),
            stderr=''
        )
        
        findings = run_bandit('/test/repo')
        assert len(findings) == 0
    
    def test_map_bandit_severity(self):
        assert _map_bandit_severity('LOW') == 'LOW'
        assert _map_bandit_severity('MEDIUM') == 'MEDIUM'
        assert _map_bandit_severity('HIGH') == 'HIGH'
        assert _map_bandit_severity('UNKNOWN') == 'MEDIUM'


class TestESLintOutputParsing:
    """Test ESLint security plugin output parsing."""
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_eslint_security_issues(self, mock_run):
        eslint_output = [
            {
                'ruleId': 'security/detect-object-injection',
                'severity': 2,
                'message': 'Potentially unsafe object property access',
                'filePath': '/test/app.js',
                'line': 25,
                'source': 'obj[variable]'
            },
            {
                'ruleId': 'no-unused-vars',
                'severity': 1,
                'message': 'Unused variable',
                'filePath': '/test/app.js',
                'line': 5,
                'source': 'const x = 1;'
            }
        ]
        
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(eslint_output),
            stderr=''
        )
        
        findings = run_eslint_security('/test/repo')
        
        assert len(findings) == 1  # Only security/* rules
        assert findings[0]['type'] == 'STATIC_ANALYSIS_FINDING'
        assert findings[0]['severity'] == 'MEDIUM'
        assert findings[0]['rule_id'] == 'security/detect-object-injection'
        assert findings[0]['tool'] == 'eslint'
    
    def test_map_eslint_severity(self):
        assert _map_eslint_severity(1) == 'LOW'
        assert _map_eslint_severity(2) == 'MEDIUM'
        assert _map_eslint_severity(3) == 'HIGH'


class TestGosecOutputParsing:
    """Test gosec output parsing."""
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_gosec_success(self, mock_run):
        gosec_output = {
            'Issues': [
                {
                    'details': 'Potential file inclusion via variable',
                    'severity': 'medium',
                    'file': '/test/main.go',
                    'line': 42,
                    'code': 'include(var)',
                    'rule_id': 'G304',
                    'cwe': {'id': 'CWE-22'}
                }
            ]
        }
        
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps(gosec_output),
            stderr=''
        )
        
        findings = run_gosec('/test/repo')
        
        assert len(findings) == 1
        assert findings[0]['type'] == 'STATIC_ANALYSIS_FINDING'
        assert findings[0]['severity'] == 'MEDIUM'
        assert findings[0]['title'] == 'Potential file inclusion via variable'
        assert findings[0]['tool'] == 'gosec'
        assert findings[0]['rule_id'] == 'G304'
        assert findings[0]['cwe'] == 'CWE-22'


class TestToolSelection:
    """Test tool selection based on project type."""
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_detect_python_project(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='/test/app.py\n/test/utils.py\n',
            stderr=''
        )
        
        languages = _detect_languages('/test/repo')
        
        assert languages['python'] is True
        assert languages['javascript'] is False
        assert languages['go'] is False
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_detect_javascript_project(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='/test/app.js\n/test/component.tsx\n',
            stderr=''
        )
        
        languages = _detect_languages('/test/repo')
        
        assert languages['python'] is False
        assert languages['javascript'] is True
        assert languages['go'] is False
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_detect_go_project(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='/test/main.go\n/test/utils.go\n',
            stderr=''
        )
        
        languages = _detect_languages('/test/repo')
        
        assert languages['python'] is False
        assert languages['javascript'] is False
        assert languages['go'] is True
    
    @patch('tasks.repo_scan.subprocess.run')
    def test_detect_mixed_project(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='/test/app.py\n/test/app.js\n/test/main.go\n',
            stderr=''
        )
        
        languages = _detect_languages('/test/repo')
        
        assert languages['python'] is True
        assert languages['javascript'] is True
        assert languages['go'] is True
