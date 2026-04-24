"""
Tests for parameter feed from katana crawl into injection tests.
Tests item 2.4 from IMPROVEMENTS.md
"""

import pytest
import json
import subprocess
from unittest.mock import patch, MagicMock
from tools.web_scanner import (
    run_katana_crawl,
    SQLI_PAYLOADS,
    XSS_PAYLOADS,
    SQLI_ERROR_PATTERNS,
    WebScanner
)


class TestKatanaOutputParsing:
    """Test parsing of katana crawler output."""

    def test_parse_valid_katana_json(self):
        """Test parsing valid katana JSON output."""
        mock_output = json.dumps({
            'url': 'http://example.com/search?q=test&page=1',
            'method': 'GET',
            'inputs': [
                {'name': 'q', 'value': 'test', 'type': 'text'},
                {'name': 'page', 'value': '1', 'type': 'hidden'}
            ]
        })

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output + '\n'
            )
            result = run_katana_crawl('http://example.com')
            
            assert len(result) == 1
            assert result[0]['url'] == 'http://example.com/search?q=test&page=1'
            assert result[0]['method'] == 'GET'
            assert len(result[0]['params']) >= 2

    def test_parse_multiple_katana_lines(self):
        """Test parsing multiple lines of katana output."""
        lines = [
            {'url': 'http://example.com/page1?id=1', 'method': 'GET'},
            {'url': 'http://example.com/login', 'method': 'POST', 'inputs': [{'name': 'username'}]},
        ]
        mock_output = '\n'.join(json.dumps(line) for line in lines)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output + '\n'
            )
            result = run_katana_crawl('http://example.com')
            
            assert len(result) == 2
            assert result[0]['url'] == 'http://example.com/page1?id=1'
            assert result[1]['method'] == 'POST'

    def test_parse_url_parameters(self):
        """Test extraction of URL query parameters."""
        line = {'url': 'http://example.com/search?q=test&sort=date&filter=all'}
        mock_output = json.dumps(line)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output + '\n'
            )
            result = run_katana_crawl('http://example.com')
            
            assert len(result) == 1
            param_names = [p['name'] for p in result[0]['params']]
            assert 'q' in param_names
            assert 'sort' in param_names
            assert 'filter' in param_names

    def test_katana_not_installed(self):
        """Test handling when katana is not installed."""
        with patch('subprocess.run', side_effect=FileNotFoundError):
            result = run_katana_crawl('http://example.com')
            assert result == []

    def test_katana_timeout(self):
        """Test handling of katana timeout."""
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='katana', timeout=70)):
            result = run_katana_crawl('http://example.com')
            assert result == []

    def test_invalid_json_line(self):
        """Test handling of invalid JSON in katana output."""
        with patch('subprocess.run') as mock_run:
            # URL with query params so it gets added to results
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"url": "http://example.com?q=test"}\ninvalid json\n'
            )
            result = run_katana_crawl('http://example.com')
            
            # Should parse the valid line and skip invalid JSON
            assert len(result) == 1
            assert result[0]['url'] == 'http://example.com?q=test'


class TestParamInjectionSQLi:
    """Test parameter injection into SQL injection tests."""

    def test_sqli_with_discovered_params(self):
        """Test SQLi detection uses discovered parameters."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = [
            {
                'url': 'http://example.com/search',
                'method': 'GET',
                'params': [{'name': 'q', 'value': 'test'}]
            }
        ]

        # Mock response with SQL error
        mock_resp = MagicMock()
        mock_resp.text = "You have an error in your SQL syntax near 'test"
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_sql_injection()
            
            # Should have found SQLi
            sqli_findings = [f for f in scanner.findings if f['type'] == 'SQL_INJECTION']
            assert len(sqli_findings) > 0
            assert sqli_findings[0]['evidence']['parameter'] == 'q'

    def test_sqli_multiple_params(self):
        """Test SQLi testing with multiple discovered parameters."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = [
            {
                'url': 'http://example.com/page',
                'method': 'GET',
                'params': [
                    {'name': 'id', 'value': '1'},
                    {'name': 'user', 'value': 'admin'}
                ]
            }
        ]

        # Only id parameter triggers SQL error
        mock_resp_id = MagicMock()
        mock_resp_id.text = "mysql_fetch_array() expects parameter"
        mock_resp_id.status_code = 200

        mock_resp_other = MagicMock()
        mock_resp_other.text = "Normal page"
        mock_resp_other.status_code = 200

        def mock_get(url, **kwargs):
            if 'id=' in url:
                return mock_resp_id
            return mock_resp_other

        with patch('requests.get', side_effect=mock_get):
            scanner.test_sql_injection()
            
            sqli_findings = [f for f in scanner.findings if f['type'] == 'SQL_INJECTION']
            assert len(sqli_findings) > 0

    def test_sqli_post_method(self):
        """Test SQLi detection with POST method parameters."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = [
            {
                'url': 'http://example.com/api/login',
                'method': 'POST',
                'params': [{'name': 'username', 'value': 'admin'}]
            }
        ]

        mock_resp = MagicMock()
        mock_resp.text = "ODBC SQL Server Driver"
        mock_resp.status_code = 200

        with patch('requests.post', return_value=mock_resp):
            scanner.test_sql_injection()
            
            sqli_findings = [f for f in scanner.findings if f['type'] == 'SQL_INJECTION']
            assert len(sqli_findings) > 0

    def test_sqli_no_discovered_params(self):
        """Test SQLi falls back to default params when none discovered."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = []

        mock_resp = MagicMock()
        mock_resp.text = "Normal page"
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_sql_injection()
            
            # Should have tried fallback params (no findings expected with normal response)
            assert len(scanner.findings) == 0

    def test_sqli_passes_discovered_params_explicitly(self):
        """Test passing discovered params explicitly to test_sql_injection."""
        scanner = WebScanner('http://example.com')

        discovered = [
            {
                'url': 'http://example.com/item',
                'method': 'GET',
                'params': [{'name': 'id', 'value': '1'}]
            }
        ]

        mock_resp = MagicMock()
        mock_resp.text = "unclosed quotation mark after the character string"
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_sql_injection(discovered_params=discovered)
            
            sqli_findings = [f for f in scanner.findings if f['type'] == 'SQL_INJECTION']
            assert len(sqli_findings) > 0


class TestParamInjectionXSS:
    """Test parameter injection into XSS tests."""

    def test_xss_with_discovered_params(self):
        """Test XSS detection uses discovered parameters."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = [
            {
                'url': 'http://example.com/search',
                'method': 'GET',
                'params': [{'name': 'q', 'value': 'test'}]
            }
        ]

        # Mock response with unencoded XSS payload reflected
        mock_resp = MagicMock()
        mock_resp.text = '<script>alert(1)</script> result for test'
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_xss_injection()
            
            xss_findings = [f for f in scanner.findings if f['type'] == 'REFLECTED_XSS']
            assert len(xss_findings) > 0

    def test_xss_multiple_payloads(self):
        """Test XSS testing with multiple payloads on discovered param."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = [
            {
                'url': 'http://example.com/search',
                'method': 'GET',
                'params': [{'name': 'q', 'value': ''}]
            }
        ]

        call_count = 0
        def mock_get(url, **kwargs):
            nonlocal call_count
            mock_resp = MagicMock()
            # Only trigger on first payload (simulate one success)
            if call_count == 0:
                mock_resp.text = '<script>alert(1)</script>'
            else:
                mock_resp.text = 'Normal page'
            mock_resp.status_code = 200
            call_count += 1
            return mock_resp

        with patch('requests.get', side_effect=mock_get):
            scanner.test_xss_injection()
            
            xss_findings = [f for f in scanner.findings if f['type'] == 'REFLECTED_XSS']
            assert len(xss_findings) > 0

    def test_xss_no_discovered_params(self):
        """Test XSS falls back when no params discovered."""
        scanner = WebScanner('http://example.com')
        scanner.discovered_params = []

        mock_resp = MagicMock()
        mock_resp.text = 'Normal page'
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_xss_injection()
            
            # Should have tried fallback
            assert len(scanner.findings) == 0

    def test_xss_passes_discovered_params_explicitly(self):
        """Test passing discovered params explicitly to test_xss_injection."""
        scanner = WebScanner('http://example.com')

        discovered = [
            {
                'url': 'http://example.com/comment',
                'method': 'GET',
                'params': [{'name': 'message', 'value': ''}]
            }
        ]

        mock_resp = MagicMock()
        mock_resp.text = '<img src=x onerror=alert(1)> posted'
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_xss_injection(discovered_params=discovered)
            
            xss_findings = [f for f in scanner.findings if f['type'] == 'REFLECTED_XSS']
            assert len(xss_findings) > 0


class TestScanFlow:
    """Test the complete scan flow with parameter feed."""

    def test_scan_calls_katana_and_injection_tests(self):
        """Test that scan() runs katana and feeds params to injection tests."""
        scanner = WebScanner('http://example.com')

        # Mock katana output
        katana_output = json.dumps({
            'url': 'http://example.com/search?q=test',
            'method': 'GET',
            'params': [{'name': 'q', 'value': 'test'}]
        })

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=katana_output + '\n'
            )
            
            with patch.object(scanner, 'test_sql_injection') as mock_sqli:
                with patch.object(scanner, 'test_xss_injection') as mock_xss:
                    with patch('requests.get') as mock_get:
                        mock_resp = MagicMock()
                        mock_resp.text = 'Normal'
                        mock_resp.status_code = 200
                        mock_get.return_value = mock_resp
                        
                        result = scanner.scan(run_crawl=True)
                        
                        # Verify katana was run
                        mock_run.assert_called_once()
                        # Verify injection tests were called
                        mock_sqli.assert_called_once()
                        mock_xss.assert_called_once()
                        # Check metadata
                        assert 'discovered_params_count' in result['metadata']

    def test_scan_without_crawl(self):
        """Test scan can run without katana crawl."""
        scanner = WebScanner('http://example.com')

        with patch.object(scanner, 'test_sql_injection') as mock_sqli:
            with patch.object(scanner, 'test_xss_injection') as mock_xss:
                with patch('requests.get') as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.text = 'Normal'
                    mock_resp.status_code = 200
                    mock_get.return_value = mock_resp
                    
                    result = scanner.scan(run_crawl=False)
                    
                    # Injection tests still called (with empty discovered_params)
                    mock_sqli.assert_called_once()
                    mock_xss.assert_called_once()

    def test_waf_info_tagged_on_findings(self):
        """Test that WAF info is tagged on findings when WAF detected."""
        scanner = WebScanner('http://example.com')
        scanner.waf_info = {
            'detected': True,
            'type': 'cloudflare',
            'details': {'indicator': 'cf-ray'}
        }
        scanner.discovered_params = [
            {
                'url': 'http://example.com/search',
                'method': 'GET',
                'params': [{'name': 'q', 'value': ''}]
            }
        ]

        mock_resp = MagicMock()
        mock_resp.text = "mysql syntax error"
        mock_resp.status_code = 200

        with patch('requests.get', return_value=mock_resp):
            scanner.test_sql_injection()
            
            sqli_findings = [f for f in scanner.findings if f['type'] == 'SQL_INJECTION']
            assert len(sqli_findings) > 0
            assert sqli_findings[0].get('waf_interference') is True
            assert sqli_findings[0].get('waf_type') == 'cloudflare'
