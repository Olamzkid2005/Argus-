"""
Custom Rule Registry - Rule sharing marketplace and versioning

Requirements: 27.4, 27.5
"""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime, UTC
from pathlib import Path


class RuleRegistry:
    """
    Manages custom rule registration, versioning, and community sharing.
    
    Provides:
    - Rule storage and retrieval
    - Versioning with rollback support
    - Community rule marketplace (basic structure)
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize rule registry.
        
        Args:
            storage_dir: Directory for rule storage
        """
        self.storage_dir = Path(storage_dir) if storage_dir else Path(os.path.dirname(__file__)) / "registry"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.versions_dir = self.storage_dir / "versions"
        self.versions_dir.mkdir(exist_ok=True)
        
        self.community_dir = self.storage_dir / "community"
        self.community_dir.mkdir(exist_ok=True)
    
    def register_rule(self, rule_id: str, rule_yaml: str, metadata: Optional[Dict] = None) -> Dict:
        """
        Register or update a rule.
        
        Args:
            rule_id: Unique rule identifier
            rule_yaml: Rule YAML content
            metadata: Optional rule metadata
            
        Returns:
            Registration result with version info
        """
        rule_file = self.storage_dir / f"{rule_id}.yml"
        
        # Determine version
        version = 1
        if rule_file.exists():
            existing = self.get_rule(rule_id)
            version = (existing.get("version", 1) + 1)
        
        # Save current version
        rule_data = {
            "id": rule_id,
            "yaml": rule_yaml,
            "version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }
        
        rule_file.write_text(rule_yaml)
        
        # Save version snapshot
        version_file = self.versions_dir / f"{rule_id}_v{version}.json"
        version_file.write_text(json.dumps(rule_data, indent=2))
        
        return rule_data
    
    def get_rule(self, rule_id: str) -> Optional[Dict]:
        """Get a rule by ID."""
        rule_file = self.storage_dir / f"{rule_id}.yml"
        if not rule_file.exists():
            return None
        
        return {
            "id": rule_id,
            "yaml": rule_file.read_text(),
            "version": self._get_current_version(rule_id),
        }
    
    def get_rule_versions(self, rule_id: str) -> List[Dict]:
        """Get all versions of a rule."""
        versions = []
        for version_file in self.versions_dir.glob(f"{rule_id}_v*.json"):
            try:
                data = json.loads(version_file.read_text())
                versions.append(data)
            except Exception:
                continue
        
        return sorted(versions, key=lambda x: x.get("version", 0), reverse=True)
    
    def rollback_rule(self, rule_id: str, target_version: int) -> Optional[Dict]:
        """
        Rollback a rule to a specific version.
        
        Args:
            rule_id: Rule identifier
            target_version: Version to rollback to
            
        Returns:
            Rolled back rule data
        """
        version_file = self.versions_dir / f"{rule_id}_v{target_version}.json"
        if not version_file.exists():
            return None
        
        version_data = json.loads(version_file.read_text())
        rule_yaml = version_data.get("yaml", "")
        
        # Re-register as new version
        return self.register_rule(
            rule_id,
            rule_yaml,
            metadata={**version_data.get("metadata", {}), "rolled_back_from": target_version}
        )
    
    def list_rules(self) -> List[Dict]:
        """List all registered rules."""
        rules = []
        for rule_file in self.storage_dir.glob("*.yml"):
            rule_id = rule_file.stem
            rules.append({
                "id": rule_id,
                "version": self._get_current_version(rule_id),
            })
        return rules
    
    def _get_current_version(self, rule_id: str) -> int:
        """Get current version number for a rule."""
        versions = self.get_rule_versions(rule_id)
        if versions:
            return max(v.get("version", 1) for v in versions)
        return 1
    
    # Community marketplace (basic structure)
    
    def publish_to_community(self, rule_id: str, author: str, description: str = "") -> Dict:
        """
        Publish a rule to the community marketplace.
        
        Args:
            rule_id: Rule identifier
            author: Rule author
            description: Rule description
            
        Returns:
            Published rule info
        """
        rule = self.get_rule(rule_id)
        if not rule:
            raise ValueError(f"Rule not found: {rule_id}")
        
        community_file = self.community_dir / f"{rule_id}.json"
        community_data = {
            "id": rule_id,
            "yaml": rule.get("yaml", ""),
            "author": author,
            "description": description,
            "published_at": datetime.now(UTC).isoformat(),
            "downloads": 0,
        }
        
        community_file.write_text(json.dumps(community_data, indent=2))
        return community_data
    
    def list_community_rules(self) -> List[Dict]:
        """List all community-published rules."""
        rules = []
        for community_file in self.community_dir.glob("*.json"):
            try:
                data = json.loads(community_file.read_text())
                rules.append(data)
            except Exception:
                continue
        return rules
    
    def download_community_rule(self, rule_id: str) -> Optional[Dict]:
        """Download a community rule into local registry."""
        community_file = self.community_dir / f"{rule_id}.json"
        if not community_file.exists():
            return None
        
        data = json.loads(community_file.read_text())
        yaml_content = data.get("yaml", "")
        
        # Update download count
        data["downloads"] = data.get("downloads", 0) + 1
        community_file.write_text(json.dumps(data, indent=2))
        
        # Register locally
        return self.register_rule(rule_id, yaml_content, metadata={"source": "community", "author": data.get("author", "")})
