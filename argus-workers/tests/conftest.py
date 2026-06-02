"""
Pytest configuration and fixtures
"""
import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Add tasks directory for loader imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tasks')))


@pytest.fixture
def sample_finding():
    """Sample finding for testing"""
    return {
        "type": "SQL_INJECTION",
        "severity": "HIGH",
        "confidence": 0.8,
        "endpoint": "https://example.com/api",
        "evidence": {
            "payload": "' OR 1=1--",
            "response": "SQL error"
        },
        "source_tool": "nuclei"
    }


@pytest.fixture
def sample_authorized_scope():
    """Sample authorized scope for testing"""
    return {
        "domains": ["staging.app.com", "*.dev.app.com"],
        "ipRanges": ["10.0.0.0/24", "192.168.1.0/24"]
    }


@pytest.fixture
def mock_db_connection_string():
    """Mock database connection string"""
    return "postgresql://test:test@localhost:5432/test_db"
