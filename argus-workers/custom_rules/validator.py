"""
Custom Rule Validator - Validates YAML-based custom rules

Requirements: 27.3
"""
import re


class RuleValidationError(Exception):
    """Raised when rule validation fails"""
    pass


class RuleValidator:
    """
    Validates custom vulnerability detection rules before execution.
    Ensures rules have required fields, valid patterns, and safe regex.
    """

    REQUIRED_FIELDS = ["id", "message", "severity"]
    ALLOWED_SEVERITIES = ["INFO", "WARNING", "ERROR", "CRITICAL", "LOW", "MEDIUM", "HIGH"]
    MAX_PATTERN_LENGTH = 5000

    # Dangerous regex patterns that could cause ReDoS
    DANGEROUS_REGEX_PATTERNS = [
        r"\(\?\!.*\)\*",  # Negative lookahead with quantifier
        r"\(\?\<\=.*\)\+",  # Positive lookbehind with quantifier
        r"\(\?\!.*\)\+",  # Negative lookahead with plus
        r"\(.*\)\{\d+,\}",  # Unbounded quantifier
        r"\(.*\)\*\*",  # Nested quantifiers
        r"\(.*\)\+\*",  # Mixed nested quantifiers
    ]

    def validate(self, rule: dict) -> tuple[bool, list[str]]:
        """
        Validate a single rule.

        Args:
            rule: Rule dictionary

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in rule:
                errors.append(f"Missing required field: {field}")

        # Validate severity
        severity = rule.get("severity", "").upper()
        if severity and severity not in self.ALLOWED_SEVERITIES:
            errors.append(f"Invalid severity: {severity}. Allowed: {self.ALLOWED_SEVERITIES}")

        # Validate pattern/regex
        patterns = rule.get("patterns", [])
        if not patterns:
            patterns = [{"pattern": rule.get("pattern", "")}]

        for pattern_def in patterns:
            if isinstance(pattern_def, str):
                pattern_def = {"pattern": pattern_def}

            regex = pattern_def.get("regex", "")
            pattern = pattern_def.get("pattern", "")

            if regex:
                if len(regex) > self.MAX_PATTERN_LENGTH:
                    errors.append(f"Regex too long: {len(regex)} chars (max {self.MAX_PATTERN_LENGTH})")

                # Check for dangerous regex
                for dangerous in self.DANGEROUS_REGEX_PATTERNS:
                    if re.search(dangerous, regex):
                        errors.append(f"Potentially dangerous regex detected: {regex[:50]}...")

                # Test regex compilation
                try:
                    re.compile(regex)
                except re.error as e:
                    errors.append(f"Invalid regex: {e}")

            if pattern and len(pattern) > self.MAX_PATTERN_LENGTH:
                errors.append(f"Pattern too long: {len(pattern)} chars (max {self.MAX_PATTERN_LENGTH})")

        # Validate ID format
        rule_id = rule.get("id", "")
        if rule_id and not re.match(r"^[a-zA-Z0-9_-]+$", rule_id):
            errors.append(f"Invalid rule ID format: {rule_id}")

        return len(errors) == 0, errors

    def validate_batch(self, rules: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        Validate multiple rules.

        Args:
            rules: List of rule dictionaries

        Returns:
            Tuple of (valid_rules, invalid_rules_with_errors)
        """
        valid = []
        invalid = []

        for rule in rules:
            is_valid, errors = self.validate(rule)
            if is_valid:
                valid.append(rule)
            else:
                invalid.append({"rule": rule, "errors": errors})

        return valid, invalid

    def validate_yaml_content(self, yaml_content: str) -> tuple[bool, list[str]]:
        """
        Validate raw YAML rule content.

        Args:
            yaml_content: YAML string containing rules

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        import yaml

        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return False, [f"Invalid YAML: {e}"]

        if not isinstance(data, dict):
            return False, ["YAML must contain a dictionary"]

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            return False, ["'rules' must be a list"]

        all_errors = []
        for i, rule in enumerate(rules):
            is_valid, errors = self.validate(rule)
            if not is_valid:
                all_errors.extend([f"Rule {i} ({rule.get('id', 'unknown')}): {e}" for e in errors])

        return len(all_errors) == 0, all_errors
