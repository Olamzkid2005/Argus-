import hashlib
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tools.web_scanner import differential_check

def test_differential_check_basic():
    # Mock baseline and test responses
    class MockResponse:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content.encode()
            self.text = content
    
    baseline = MockResponse(200, "Welcome admin")
    test = MockResponse(200, "Welcome admin")
    baseline_hash = hashlib.md5(b"Welcome admin").hexdigest()
    
    is_vuln, conf, evidence = differential_check(baseline, test, baseline_hash, "test")
    assert not is_vuln  # Same response = not vulnerable
