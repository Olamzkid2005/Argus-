import pytest
import time
import requests
from unittest.mock import patch, MagicMock
from tools.web_scanner import (
    SQL_TIME_PAYLOADS,
    CMD_TIME_PAYLOADS,
    check_time_based_injection,
    WebScanner
)


def test_sql_time_payloads_exist():
    """Verify SQL time-based payloads are defined correctly."""
    assert len(SQL_TIME_PAYLOADS) == 4
    assert any("SLEEP(5)" in p for p in SQL_TIME_PAYLOADS)
    assert any("WAITFOR DELAY" in p for p in SQL_TIME_PAYLOADS)
    assert any("BENCHMARK" in p for p in SQL_TIME_PAYLOADS)


def test_cmd_time_payloads_exist():
    """Verify command injection time-based payloads are defined correctly."""
    assert len(CMD_TIME_PAYLOADS) == 4
    assert any("sleep 5" in p for p in CMD_TIME_PAYLOADS)
    assert any("$(sleep 5)" in p for p in CMD_TIME_PAYLOADS)


@patch("tools.web_scanner.requests.get")
def test_time_based_injection_detected(mock_get):
    """Test that time-based injection is detected when response time exceeds threshold."""
    mock_response = MagicMock()
    mock_response.text = "normal response"
    mock_response.headers = {}
    mock_get.return_value = mock_response

    # Simulate 6 seconds elapsed, base_time is 1 (threshold is base + 4 = 5)
    with patch("tools.web_scanner.time.time", side_effect=[0, 6.0]):
        injected, elapsed = check_time_based_injection(
            "http://example.com", "param", "1' AND SLEEP(5)--", 1.0
        )
        assert injected is True
        assert elapsed == 6.0


@patch("tools.web_scanner.requests.get")
def test_time_based_injection_not_detected(mock_get):
    """Test that time-based injection is not detected when response time is within threshold."""
    mock_response = MagicMock()
    mock_response.text = "normal response"
    mock_response.headers = {}
    mock_get.return_value = mock_response

    # Simulate 2 seconds elapsed, base_time is 1 (threshold is 5)
    with patch("tools.web_scanner.time.time", side_effect=[0, 2.0]):
        injected, elapsed = check_time_based_injection(
            "http://example.com", "param", "1' AND SLEEP(5)--", 1.0
        )
        assert injected is False
        assert elapsed == 2.0


@patch("tools.web_scanner.requests.get")
def test_time_based_injection_request_exception(mock_get):
    """Test that failed requests return False."""
    mock_get.side_effect = requests.RequestException("Connection failed")
    injected, elapsed = check_time_based_injection(
        "http://example.com", "param", "SLEEP(5)", 1.0
    )
    assert injected is False
    assert elapsed == 0.0


@patch("tools.web_scanner.requests.get")
def test_web_scanner_baseline_time(mock_get):
    """Test that WebScanner measures baseline response time correctly."""
    mock_response = MagicMock()
    mock_response.text = "normal response"
    mock_response.headers = {}
    mock_get.return_value = mock_response

    # Time call order during scan():
    # 1. start = time.time() → 0
    # 2. can_request: now = time.time() → 0
    # 3. record_request: time.time() → 0
    # 4. self.base_time = time.time() - start → 1.5
    time_values = [0, 0, 0, 1.5]
    call_log = []
    
    def mock_time():
        val = time_values.pop(0)
        call_log.append(val)
        return val

    with patch("time.time", side_effect=mock_time):
        scanner = WebScanner("http://example.com")
        # Disable other injection tests to avoid extra time calls
        scanner.test_sql_injection = lambda *a, **kw: None
        scanner.test_xss_injection = lambda *a, **kw: None
        scanner.test_time_based_injections = lambda *a, **kw: None
        result = scanner.scan(run_crawl=False)
        print(f"Time calls: {call_log}")
        print(f"Base time: {scanner.base_time}")
        assert scanner.base_time == 1.5
        assert result["metadata"]["base_response_time"] == 1.5
