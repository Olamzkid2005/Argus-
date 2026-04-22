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

    def test_load_rules_from_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = os.path.join(tmpdir, "test.yml")
            with open(rule_file, "w") as f:
                f.write("""
rules:
  - id: test-rule-1
    message: Test SQL Injection
    severity: HIGH
    patterns:
      - regex: "SELECT.*FROM.*WHERE.*=.*"
    category: injection
""")
            engine = CustomRuleEngine(rules_dir=tmpdir)
            assert len(engine.rules) == 1
            assert engine.rules[0]["id"] == "test-rule-1"

    def test_add_rule(self):
        engine = CustomRuleEngine()
        rule = {"id": "test-regex", "message": "Hardcoded Secret", "severity": "CRITICAL", "patterns": [{"regex": "API_KEY\\s*=\\s*[\"'][^\"']+[\"']"}]}
        engine.add_rule(rule)
        assert len(engine.rules) == 1

    def test_execute_regex_rule(self):
        engine = CustomRuleEngine()
        rule = {
            "id": "test-regex",
            "message": "Hardcoded Secret",
            "severity": "CRITICAL",
            "patterns": [{"regex": "API_KEY\\s*=\\s*[\"'][^\"']+[\"']"}]
        }
        engine.add_rule(rule)
        content = "const API_KEY = 'sk-1234567890abcdef';"
        findings = engine.execute(content, "test.js")
        assert len(findings) == 1
        assert findings[0]["type"] == "test-regex"
        assert findings[0]["severity"] == "CRITICAL"

    def test_execute_no_match(self):
        engine = CustomRuleEngine()
        rule = {
            "id": "test-no-match",
            "message": "No Match Rule",
            "severity": "LOW",
            "patterns": [{"regex": "zzzzzzzzz"}]
        }
        engine.add_rule(rule)
        findings = engine.execute("hello world", "test.txt")
        assert findings == []

    def test_execute_keyword_rule(self):
        engine = CustomRuleEngine()
        rule = {
            "id": "test-keyword",
            "message": "Dangerous Function",
            "severity": "HIGH",
            "patterns": [{"pattern": "eval("}, {"pattern": "exec("}]
        }
        engine.add_rule(rule)
        content = "eval(user_input);"
        findings = engine.execute(content, "test.py")
        assert len(findings) == 1


class TestRuleValidator:
    """Test RuleValidator"""

    @pytest.fixture
    def validator(self):
        return RuleValidator()

    def test_valid_rule(self, validator):
        rule = {
            "id": "valid-rule",
            "message": "Valid Rule",
            "severity": "HIGH",
            "patterns": [{"regex": "test.*pattern"}]
        }
        is_valid, errors = validator.validate(rule)
        assert is_valid is True
        assert errors == []

    def test_missing_required_field(self, validator):
        rule = {"id": "bad-rule"}
        is_valid, errors = validator.validate(rule)
        assert is_valid is False
        assert any("message" in e for e in errors)

    def test_invalid_severity(self, validator):
        rule = {
            "id": "bad-severity",
            "message": "Bad Severity",
            "severity": "INVALID",
            "patterns": [{"regex": "test"}]
        }
        is_valid, errors = validator.validate(rule)
        assert is_valid is False
        assert any("severity" in e.lower() for e in errors)

    def test_invalid_regex(self, validator):
        rule = {
            "id": "bad-regex",
            "message": "Bad Regex",
            "severity": "LOW",
            "patterns": [{"regex": "[invalid("}]
        }
        is_valid, errors = validator.validate(rule)
        assert is_valid is False
        assert any("regex" in e.lower() or "compile" in e.lower() for e in errors)


class TestRuleRegistry:
    """Test RuleRegistry"""

    @pytest.fixture
    def registry(self, tmpdir):
        return RuleRegistry(storage_dir=str(tmpdir))

    def test_register_rule(self, registry):
        result = registry.register_rule("reg-1", "id: reg-1\nmessage: Registered Rule\nseverity: MEDIUM\npatterns:\n  - regex: test")
        assert result["id"] == "reg-1"
        assert result["version"] == 1

    def test_update_rule_creates_version(self, registry):
        registry.register_rule("reg-2", "id: reg-2\nmessage: Rule\nseverity: MEDIUM\npatterns:\n  - regex: test")
        result = registry.register_rule("reg-2", "id: reg-2\nmessage: Updated Rule\nseverity: MEDIUM\npatterns:\n  - regex: test")
        assert result["version"] == 2
        assert len(registry.get_rule_versions("reg-2")) == 2

    def test_rollback_rule(self, registry):
        registry.register_rule("reg-3", "id: reg-3\nmessage: Original\nseverity: MEDIUM\npatterns:\n  - regex: test")
        registry.register_rule("reg-3", "id: reg-3\nmessage: Changed\nseverity: MEDIUM\npatterns:\n  - regex: test")
        result = registry.rollback_rule("reg-3", 1)
        assert result is not None
        assert result["version"] == 3

    def test_community_share(self, registry):
        registry.register_rule("comm-1", "id: comm-1\nmessage: Community Rule\nseverity: LOW\npatterns:\n  - regex: test")
        result = registry.publish_to_community("comm-1", "test_author")
        assert result["author"] == "test_author"
        assert result["downloads"] == 0

    def test_get_community_rules(self, registry):
        registry.register_rule("comm-2", "id: comm-2\nmessage: Shared Rule\nseverity: LOW\npatterns:\n  - regex: test")
        registry.publish_to_community("comm-2", "author")
        community = registry.list_community_rules()
        assert len(community) == 1
        assert community[0]["id"] == "comm-2"

    def test_download_community_rule(self, registry):
        registry.register_rule("comm-3", "id: comm-3\nmessage: Downloadable\nseverity: LOW\npatterns:\n  - regex: test")
        registry.publish_to_community("comm-3", "author")
        result = registry.download_community_rule("comm-3")
        assert result is not None
        assert result["id"] == "comm-3"
