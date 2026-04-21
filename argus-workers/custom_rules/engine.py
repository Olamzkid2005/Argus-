"""
Custom Rule Engine - YAML-based vulnerability detection

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5
"""
import re
import yaml
from typing import Dict, List, Optional
from pathlib import Path


class CustomRuleError(Exception):
    """Raised when a custom rule is invalid or fails execution"""
    pass


class CustomRuleEngine:
    """
    Executes YAML-based custom vulnerability detection rules.
    
    Rules define patterns to match against text content,
    with severity, confidence, and metadata.
    """
    
    def __init__(self, rules_dir: Optional[str] = None):
        """
        Initialize rule engine.
        
        Args:
            rules_dir: Directory containing YAML rule files
        """
        self.rules_dir = Path(rules_dir) if rules_dir else None
        self.rules: List[Dict] = []
        
        if self.rules_dir and self.rules_dir.exists():
            self._load_rules()
    
    def _load_rules(self):
        """Load all YAML rule files from rules directory."""
        if not self.rules_dir:
            return
        
        for rule_file in self.rules_dir.glob("*.yml"):
            try:
                rule_data = yaml.safe_load(rule_file.read_text())
                if isinstance(rule_data, dict) and "rules" in rule_data:
                    for rule in rule_data["rules"]:
                        rule["_source_file"] = str(rule_file.name)
                        self.rules.append(rule)
                elif isinstance(rule_data, dict) and "id" in rule_data:
                    rule_data["_source_file"] = str(rule_file.name)
                    self.rules.append(rule_data)
            except Exception as e:
                raise CustomRuleError(f"Failed to load rule {rule_file}: {e}")
    
    def add_rule(self, rule: Dict):
        """Add a single rule to the engine."""
        self.rules.append(rule)
    
    def execute(self, content: str, source_path: str = "") -> List[Dict]:
        """
        Execute all loaded rules against content.
        
        Args:
            content: Text content to scan
            source_path: Optional source identifier (file path, URL, etc.)
            
        Returns:
            List of matched findings
        """
        findings = []
        
        for rule in self.rules:
            try:
                matches = self._match_rule(rule, content)
                for match in matches:
                    findings.append({
                        "type": rule.get("id", "CUSTOM_RULE"),
                        "severity": rule.get("severity", "INFO").upper(),
                        "endpoint": source_path,
                        "evidence": {
                            "message": rule.get("message", ""),
                            "matched_text": match.get("matched", "")[:200],
                            "line": match.get("line", 0),
                            "rule_id": rule.get("id", ""),
                            "category": rule.get("metadata", {}).get("category", "custom"),
                        },
                        "confidence": rule.get("metadata", {}).get("confidence", 0.80),
                        "tool": "custom_rule_engine",
                    })
            except Exception as e:
                raise CustomRuleError(f"Rule {rule.get('id', 'unknown')} failed: {e}")
        
        return findings
    
    def _match_rule(self, rule: Dict, content: str) -> List[Dict]:
        """Match a single rule against content."""
        matches = []
        lines = content.split("\n")
        
        patterns = rule.get("patterns", [])
        if not patterns:
            # Single pattern
            pattern = rule.get("pattern")
            if pattern:
                patterns = [{"pattern": pattern}]
        
        for pattern_def in patterns:
            if isinstance(pattern_def, str):
                pattern_def = {"pattern": pattern_def}
            
            pattern = pattern_def.get("pattern", "")
            regex = pattern_def.get("regex", "")
            
            if regex:
                for line_num, line in enumerate(lines, 1):
                    if re.search(regex, line):
                        matches.append({"matched": line, "line": line_num})
            elif pattern:
                for line_num, line in enumerate(lines, 1):
                    if pattern in line:
                        matches.append({"matched": line, "line": line_num})
        
        return matches
    
    def execute_against_file(self, file_path: str) -> List[Dict]:
        """
        Execute rules against a file.
        
        Args:
            file_path: Path to file to scan
            
        Returns:
            List of matched findings
        """
        path = Path(file_path)
        if not path.exists():
            return []
        
        content = path.read_text(errors="ignore")
        return self.execute(content, source_path=str(path))
    
    def get_rule_by_id(self, rule_id: str) -> Optional[Dict]:
        """Find a loaded rule by ID."""
        for rule in self.rules:
            if rule.get("id") == rule_id:
                return rule
        return None
