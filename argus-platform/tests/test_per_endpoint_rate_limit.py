import time
import pytest
from tools.web_scanner import PerEndpointRateLimiter


def test_limiter_initialization():
    limiter = PerEndpointRateLimiter(default_rps=5)
    assert limiter.default_rps == 5
    assert limiter.endpoint_limits == {}
    assert len(limiter.endpoint_stats) == 0


def test_record_request():
    limiter = PerEndpointRateLimiter()
    endpoint = "https://example.com"
    limiter.record_request(endpoint)
    assert len(limiter.endpoint_stats[endpoint]["requests"]) == 1
    assert limiter.endpoint_stats[endpoint]["last_request"] == 0  # Unused but initialized


def test_can_request_under_limit():
    limiter = PerEndpointRateLimiter(default_rps=10)
    endpoint = "https://example.com"
    assert limiter.can_request(endpoint) is True


def test_can_request_over_limit():
    limiter = PerEndpointRateLimiter(default_rps=1)  # 1 req/sec = 60 req/min
    endpoint = "https://example.com"
    for _ in range(60):
        limiter.record_request(endpoint)
    assert limiter.can_request(endpoint) is False


def test_custom_endpoint_limit():
    limiter = PerEndpointRateLimiter(default_rps=10)
    endpoint = "https://example.com"
    limiter.set_limit(endpoint, 2)  # 2 req/sec = 120 req/min
    assert limiter.endpoint_limits[endpoint] == 2
    for _ in range(120):
        limiter.record_request(endpoint)
    assert limiter.can_request(endpoint) is False


def test_per_endpoint_isolation():
    limiter = PerEndpointRateLimiter(default_rps=1)  # 60 req/min per endpoint
    endpoint_a = "https://a.com"
    endpoint_b = "https://b.com"
    for _ in range(60):
        limiter.record_request(endpoint_a)
    assert limiter.can_request(endpoint_a) is False
    assert limiter.can_request(endpoint_b) is True


def test_old_requests_cleaned():
    limiter = PerEndpointRateLimiter(default_rps=10)
    endpoint = "https://example.com"
    # Add request older than 60 seconds
    old_time = time.time() - 61
    limiter.endpoint_stats[endpoint]["requests"].append(old_time)
    # Add recent request
    limiter.record_request(endpoint)
    # can_request cleans old requests, so only 1 recent request remains
    assert limiter.can_request(endpoint) is True
    assert len(limiter.endpoint_stats[endpoint]["requests"]) == 1
