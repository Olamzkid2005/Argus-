"""
Tests for security features: evidence sanitization and secrets redaction
"""
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestEvidenceSanitization:
    """Test evidence sanitization prevents XSS"""

    def test_sanitize_string_escapes_html(self):
        """HTML entities should be escaped"""
        from utils.sanitization import sanitize_string
        
        result = sanitize_string('<script>alert(1)</script>')
        assert '&lt;script&gt;' in result
        assert '<script>' not in result

    def test_sanitize_string_escapes_entities(self):
        """HTML entities should be escaped"""
        from utils.sanitization import sanitize_string
        
        result = sanitize_string('test & "quoted"')
        assert '&amp;' in result
        assert '&quot;' in result

    def test_sanitize_evidence_recursive(self):
        """Sanitize evidence dict recursively"""
        from utils.sanitization import sanitize_evidence
        
        evidence = {
            "payload": '<img src=x onerror=alert(1)>',
            "nested": {
                "value": "<script>evil()</script>"
            },
            "list": ["<div>", "safe text"]
        }
        
        result = sanitize_evidence(evidence)
        
        assert '&lt;img' in result["payload"]
        assert '&lt;script&gt;' in result["nested"]["value"]
        assert '&lt;div&gt;' in result["list"][0]
        assert result["list"][1] == "safe text"

    def test_check_for_dangerous_content(self):
        """Detect dangerous patterns"""
        from utils.sanitization import check_for_dangerous_content
        
        # Script tag detection
        result = check_for_dangerous_content('<script>alert(1)</script>')
        assert 'script tag' in result
        
        # Event handler detection
        result = check_for_dangerous_content('<img onerror=alert(1)>')
        assert 'event handler' in result
        
        # javascript: protocol
        result = check_for_dangerous_content('javascript:alert(1)')
        assert 'javascript: protocol' in result

    def test_strip_dangerous_tags(self):
        """Remove dangerous tags"""
        from utils.sanitization import strip_dangerous_tags
        
        result = strip_dangerous_tags('<script>evil</script>text')
        assert '<script>' not in result
        assert 'text' in result


class TestSecretsRedaction:
    """Test secrets redaction in logs"""

    def test_redact_password_in_string(self):
        """Password should be redacted"""
        from utils.logging_utils import redact_string
        
        result = redact_string('password=secret123')
        assert 'secret123' not in result
        assert '****' in result or 'REDACTED' in result

    def test_redact_api_key(self):
        """API keys should be redacted"""
        from utils.logging_utils import redact_string
        
        result = redact_string('api_key=sk_live_abc123xyz')
        assert 'sk_live_' not in result

    def test_redact_jwt(self):
        """JWT tokens should be fully redacted"""
        from utils.logging_utils import redact_string
        
        jwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
        result = redact_string(jwt)
        assert result == '[REDACTED]'

    def test_redact_dict_sensitive_keys(self):
        """Sensitive dict keys should be redacted"""
        from utils.logging_utils import redact_dict
        
        data = {
            "username": "john",
            "password": "secret123",
            "token": "abc123xyz",
            "nested": {
                "api_key": "sk_test_123"
            }
        }
        
        result = redact_dict(data)
        
        assert result["password"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["nested"]["api_key"] == "[REDACTED]"
        assert result["username"] == "john"

    def test_redact_dict_non_sensitive(self):
        """Non-sensitive keys should not be redacted"""
        from utils.logging_utils import redact_dict
        
        data = {
            "name": "test",
            "count": 42,
            "enabled": True
        }
        
        result = redact_dict(data)
        
        assert result["name"] == "test"
        assert result["count"] == 42
        assert result["enabled"] is True

    def test_redact_aws_credentials(self):
        """AWS credentials should be redacted"""
        from utils.logging_utils import redact_string
        
        # AWS Access Key
        result = redact_string('AKIAIOSFODNN7EXAMPLE')
        assert result == '[REDACTED]'
        
        # AWS Secret Key - pattern needs to match
        result = redact_string('aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')
        assert 'EXAMPLEKEY' not in result

    def test_redact_private_key(self):
        """Private keys should be redacted"""
        from utils.logging_utils import redact_string
        
        result = redact_string('-----BEGIN RSA PRIVATE KEY-----')
        assert result == '[REDACTED]'

    def test_redact_database_url(self):
        """Database URLs should be partially redacted"""
        from utils.logging_utils import redact_string
        
        # Test with specific DB URL format
        result = redact_string('postgresql://user:password@localhost:5432/db')
        # URL password should redact the password portion
        assert ':password@' not in result
        assert 'localhost:5432' in result