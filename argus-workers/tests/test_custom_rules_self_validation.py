"""
Self-validation test: every bugbounty YAML rule must match its own test_patterns
and must NOT match its non_matching_patterns.
"""
import re
from pathlib import Path

import yaml


def test_all_bugbounty_rules_match_their_examples():
    """Every bugbounty rule must match all test_patterns and reject non_matching_patterns."""
    rules_dir = Path(__file__).parent.parent / "custom_rules" / "bugbounty_rules"

    assert rules_dir.exists(), f"Rules directory not found: {rules_dir}"

    failures = []

    for rule_file in sorted(rules_dir.glob("*.yaml")):
        yaml_data = yaml.safe_load(rule_file.read_text())
        rules = yaml_data.get("rules", [])
        if not rules:
            failures.append(f"File {rule_file.name}: no rules found")
            continue

        for rule in rules:
            rule_id = rule.get("id", "UNKNOWN")
            patterns = rule.get("patterns", [])

            if not patterns:
                failures.append(f"Rule {rule_id}: no patterns defined")
                continue

            # Test that test_patterns all match
            test_patterns = rule.get("test_patterns", [])
            if not test_patterns:
                failures.append(f"Rule {rule_id}: missing test_patterns")
            else:
                for i, test_str in enumerate(test_patterns):
                    matched = False
                    for pe in patterns:
                        if isinstance(pe, str):
                            pe = {"regex": pe}
                        regex = pe.get("regex", "") or pe.get("pattern", "")
                        if regex:
                            try:
                                if re.search(regex, test_str, re.IGNORECASE):
                                    matched = True
                                    break
                            except re.error as e:
                                failures.append(
                                    f"Rule {rule_id}: invalid regex in pattern: {e}"
                                )
                                break
                    if not matched:
                        failures.append(
                            f"Rule {rule_id} test_pattern[{i}] NOT matched: {test_str[:80]}"
                        )

            # Test that non_matching_patterns are NOT matched
            non_matches = rule.get("non_matching_patterns", [])
            for i, test_str in enumerate(non_matches):
                for pe in patterns:
                    if isinstance(pe, str):
                        pe = {"regex": pe}
                    regex = pe.get("regex", "") or pe.get("pattern", "")
                    if regex:
                        try:
                            if re.search(regex, test_str, re.IGNORECASE):
                                failures.append(
                                    f"Rule {rule_id} non_matching[{i}] INCORRECTLY matched: {test_str[:80]}"
                                )
                        except re.error:
                            pass

    assert not failures, "\n".join(failures)
