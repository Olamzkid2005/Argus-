"""
Tests for Custom Rule Engine
"""
import pytest
import tempfile
import os
from custom_rules.engine import CustomRuleEngine
from custom_rules.validator import RuleValidator
from custom_rules.registry import RuleRegistry


class TestCustomRuleEngine:
    """Test CustomRuleEngine"""

    @pytest.fixture
    def engine(self):
        return CustomRuleEngine()

    def test_load_yaml_rules(self, engine):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
rules:
  - id: test-rule-1
    name: Test SQL Injection
    severity: HIGH
    pattern: "SELECT.*FROM.*WHERE.*=.*\\$.*"
    category: injection
    description: "Detects potential SQL injection"
""")
            temp_path = f.name
        try:
            rules = engine.load_rules(temp_path)
            assert len(rules) == 1
            assert rules[0]["id"] == "test-rule-1"
            assert rules[0]["severity"] == "HIGH"
        finally:
            os.unlink(temp_path)

    def test_execute_regex_rule(self, engine):
        rule = {
            "id": "test-regex",
            "name": "Hardcoded Secret",
            "severity": "CRITICAL",
            "pattern": "API_KEY\\s*=\\s*[\"'][^\"']+[\"']",
            "category": "secrets"
        }
        content = "const API_KEY = 'sk-1234567890abcdef';"
        findings = engine.execute_rule(rule, content, "test.js")
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "test-regex"
        assert findings[0]["severity"] == "CRITICAL"

    def test_execute_no_match(self, engine):
        rule = {
            "id": "test-no-match",
            "name": "No Match Rule",
            "severity": "LOW",
            "pattern": "zzzzzzzzz",
            "category": "test"
        }
        findings = engine.execute_rule(rule, "hello world", "test.txt")
        assert findings == []

    def test_execute_keyword_rule(self, engine):
        rule = {
            "id": "test-keyword",
            "name": "Dangerous Function",
            "severity": "HIGH",
            "keywords": ["eval(", "exec("],
            "category": "code-quality"
        }
        content = "eval(user_input);"
        findings = engine.execute_rule(rule, content, "test.py")
        assert len(findings) == 1
        assert findings[0]["matched_keyword"] == "eval("


class TestRuleValidator:
    """Test RuleValidator"""

    @pytest.fixture
    def validator(self):
        return RuleValidator()

    def test_valid_rule(self, validator):
        rule = {
            "id": "valid-rule",
            "name": "Valid Rule",
            "severity": "HIGH",
            "pattern": "test.*pattern",
            "category": "test"
        }
        result = validator.validate(rule)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_required_field(self, validator):
        rule = {"id": "bad-rule"}
        result = validator.validate(rule)
        assert result["valid"] is False
        assert any("name" in e for e in result["errors"])

    def test_invalid_severity(self, validator):
        rule = {
            "id": "bad-severity",
            "name": "Bad Severity",
            "severity": "INVALID",
            "pattern": "test"
        }
        result = validator.validate(rule)
        assert result["valid"] is False
        assert any("severity" in e.lower() for e in result["errors"])

    def test_invalid_regex(self, validator):
        rule = {
            "id": "bad-regex",
            "name": "Bad Regex",
            "severity": "LOW",
            "pattern": "[invalid("
        }
        result = validator.validate(rule)
        assert result["valid"] is False
        assert any("regex" in e.lower() for e in result["errors"])


class TestRuleRegistry:
    """Test RuleRegistry"""

    @pytest.fixture
    def registry(self):
        return RuleRegistry()

    def test_register_rule(self, registry):
        rule = {"id": "reg-1", "name": "Registered Rule", "severity": "MEDIUM", "pattern": "test"}
        registry.register(rule)
        assert "reg-1" in registry.rules
        assert registry.rules["reg-1"]["version"] == 1

    def test_update_rule_creates_version(self, registry):
        rule = {"id": "reg-2", "name": "Rule", "severity": "MEDIUM", "pattern": "test"}
        registry.register(rule)
        rule["name"] = "Updated Rule"
        registry.update("reg-2", rule)
        assert registry.rules["reg-2"]["version"] == 2
        assert len(registry.get_versions("reg-2")) == 2

    def test_rollback_rule(self, registry):
        rule = {"id": "reg-3", "name": "Original", "severity": "MEDIUM", "pattern": "test"}
        registry.register(rule)
        rule["name"] = "Changed"
        registry.update("reg-3", rule)
        success = registry.rollback("reg-3", 1)
        assert success is True
        assert registry.rules["reg-3"]["name"] == "Original"
        assert registry.rules["reg-3"]["version"] == 3

    def test_community_share(self, registry):
        rule = {"id": "comm-1", "name": "Community Rule", "severity": "LOW", "pattern": "test"}
        registry.register(rule)
        registry.share_to_community("comm-1")
        assert registry.rules["comm-1"]["is_community_shared"] is True

    def test_get_community_rules(self, registry):
        rule = {"id": "comm-2", "name": "Shared Rule", "severity": "LOW", "pattern": "test"}
        registry.register(rule)
        registry.share_to_community("comm-2")
        community = registry.get_community_rules()
        assert len(community) == 1
        assert community[0]["id"] == "comm-2"
