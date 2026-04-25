"""
Tool Adapter Registry with Versioning

Manages tool adapters with schema versioning to handle
tool output format changes gracefully.

Requirements: 34.1, 34.2, 34.3, 34.4, 34.5
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from abc import ABC, abstractmethod
import json

logger = logging.getLogger(__name__)


class AdapterNotFound(Exception):
    """Raised when no adapter exists for tool/version"""
    pass


class SchemaMismatch(Exception):
    """Raised when tool output doesn't match expected schema"""
    pass


@dataclass
class ToolAdapterMetadata:
    """Metadata for a tool adapter."""
    tool_name: str
    schema_version: str
    parser_class: type
    expected_schema: Dict
    description: str


class BaseToolAdapter(ABC):
    """Base class for versioned tool adapters."""
    
    @abstractmethod
    def validate_schema(self, raw_output: str) -> bool:
        """
        Validate that tool output matches expected schema.
        
        Args:
            raw_output: Raw tool output
        
        Returns:
            True if schema matches, False otherwise
        """
        pass
    
    @abstractmethod
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse tool output into structured findings.
        
        Args:
            raw_output: Raw tool output
        
        Returns:
            List of parsed findings
        """
        pass


class NucleiAdapterV1(BaseToolAdapter):
    """Nuclei adapter for schema version 1.x (JSON lines)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        """Validate nuclei JSON lines format."""
        if not raw_output.strip():
            return True  # Empty output is valid
        
        # Check first non-empty line is valid JSON with expected fields
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                # Check for expected fields
                required_fields = ["info", "matched-at"]
                return all(field in data for field in required_fields)
            except json.JSONDecodeError:
                return False
        
        return True
    
    def parse(self, raw_output: str) -> List[Dict]:
        """Parse nuclei JSON lines output."""
        from parsers.parser import NucleiParser
        parser = NucleiParser()
        return parser.parse(raw_output)


class HttpxAdapterV1(BaseToolAdapter):
    """Httpx adapter for schema version 1.x (JSON or plain URLs)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        """Validate httpx output format."""
        if not raw_output.strip():
            return True
        
        # Check first line is either JSON or URL
        first_line = raw_output.split("\n")[0].strip()
        
        # Try JSON
        try:
            json.loads(first_line)
            return True
        except json.JSONDecodeError:
            pass
        
        # Try URL
        return first_line.startswith("http://") or first_line.startswith("https://")
    
    def parse(self, raw_output: str) -> List[Dict]:
        """Parse httpx output."""
        from parsers.parser import HttpxParser
        parser = HttpxParser()
        return parser.parse(raw_output)


class KatanaAdapterV1(BaseToolAdapter):
    """Katana adapter for schema version 1.x (JSON lines)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if "request" in data:
                    return True
            except json.JSONDecodeError:
                pass
        return True
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import KatanaParser
        parser = KatanaParser()
        return parser.parse(raw_output)


class GauAdapterV1(BaseToolAdapter):
    """Gau adapter for schema version 1.x (plain URLs)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        first_line = raw_output.split("\n")[0].strip()
        return first_line.startswith("http://") or first_line.startswith("https://")
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import GauParser
        parser = GauParser()
        return parser.parse(raw_output)


class WaybackurlsAdapterV1(BaseToolAdapter):
    """Waybackurls adapter for schema version 1.x (plain URLs)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        first_line = raw_output.split("\n")[0].strip()
        return first_line.startswith("http://") or first_line.startswith("https://")
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import WaybackurlsParser
        parser = WaybackurlsParser()
        return parser.parse(raw_output)


class ArjunAdapterV1(BaseToolAdapter):
    """Arjun adapter for schema version 1.x (JSON)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        try:
            data = json.loads(raw_output)
            return isinstance(data, (dict, list))
        except json.JSONDecodeError:
            return False
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import ArjunParser
        parser = ArjunParser()
        return parser.parse(raw_output)


class DalfoxAdapterV1(BaseToolAdapter):
    """Dalfox adapter for schema version 1.x (JSON lines)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if "url" in data or "param" in data:
                    return True
            except json.JSONDecodeError:
                pass
        return True
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import DalfoxParser
        parser = DalfoxParser()
        return parser.parse(raw_output)


class JwtToolAdapterV1(BaseToolAdapter):
    """JWT Tool adapter for schema version 1.x (JSON)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        try:
            data = json.loads(raw_output)
            return "vulnerabilities" in data or "token" in data
        except json.JSONDecodeError:
            return False
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import JwtToolParser
        parser = JwtToolParser()
        return parser.parse(raw_output)


class CommixAdapterV1(BaseToolAdapter):
    """Commix adapter for schema version 1.x (text)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        # Commix outputs text, accept any non-empty
        return bool(raw_output.strip())
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import CommixParser
        parser = CommixParser()
        return parser.parse(raw_output)


class SemgrepAdapterV1(BaseToolAdapter):
    """Semgrep adapter for schema version 1.x (JSON)."""
    
    def validate_schema(self, raw_output: str) -> bool:
        if not raw_output.strip():
            return True
        try:
            data = json.loads(raw_output)
            return "results" in data or isinstance(data, list)
        except json.JSONDecodeError:
            return False
    
    def parse(self, raw_output: str) -> List[Dict]:
        from parsers.parser import SemgrepParser
        parser = SemgrepParser()
        return parser.parse(raw_output)


class ToolAdapterRegistry:
    """
    Registry for tool adapters with versioning support.
    
    Manages multiple versions of tool adapters and selects
    the appropriate one based on tool name and version.
    """
    
    def __init__(self):
        """Initialize registry."""
        self.adapters: Dict[str, Dict[str, ToolAdapterMetadata]] = {}
        self._register_default_adapters()
    
    def _register_default_adapters(self) -> None:
        """Register default tool adapters."""
        # Nuclei v1
        self.register_adapter(
            tool_name="nuclei",
            schema_version="1.x",
            adapter_class=NucleiAdapterV1,
            expected_schema={
                "type": "object",
                "required": ["info", "matched-at"],
                "properties": {
                    "info": {"type": "object"},
                    "matched-at": {"type": "string"}
                }
            },
            description="Nuclei JSON lines output format"
        )
        
        # Httpx v1
        self.register_adapter(
            tool_name="httpx",
            schema_version="1.x",
            adapter_class=HttpxAdapterV1,
            expected_schema={
                "oneOf": [
                    {"type": "object", "required": ["url"]},
                    {"type": "string", "pattern": "^https?://"}
                ]
            },
            description="Httpx JSON or plain URL output"
        )
        
        # Katana v1
        self.register_adapter(
            tool_name="katana",
            schema_version="1.x",
            adapter_class=KatanaAdapterV1,
            expected_schema={
                "type": "object",
                "properties": {
                    "request": {"type": "object"}
                }
            },
            description="Katana JSON lines output"
        )
        
        # Gau v1
        self.register_adapter(
            tool_name="gau",
            schema_version="1.x",
            adapter_class=GauAdapterV1,
            expected_schema={
                "type": "string",
                "pattern": "^https?://"
            },
            description="Gau plain URL output"
        )
        
        # Waybackurls v1
        self.register_adapter(
            tool_name="waybackurls",
            schema_version="1.x",
            adapter_class=WaybackurlsAdapterV1,
            expected_schema={
                "type": "string",
                "pattern": "^https?://"
            },
            description="Waybackurls plain URL output"
        )
        
        # Arjun v1
        self.register_adapter(
            tool_name="arjun",
            schema_version="1.x",
            adapter_class=ArjunAdapterV1,
            expected_schema={
                "oneOf": [
                    {"type": "array"},
                    {"type": "object", "properties": {"params": {"type": "array"}}}
                ]
            },
            description="Arjun JSON output"
        )
        
        # Dalfox v1
        self.register_adapter(
            tool_name="dalfox",
            schema_version="1.x",
            adapter_class=DalfoxAdapterV1,
            expected_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "param": {"type": "string"}
                }
            },
            description="Dalfox JSON lines output"
        )
        
        # JWT Tool v1
        self.register_adapter(
            tool_name="jwt_tool",
            schema_version="1.x",
            adapter_class=JwtToolAdapterV1,
            expected_schema={
                "type": "object",
                "properties": {
                    "vulnerabilities": {"type": "array"},
                    "token": {"type": "object"}
                }
            },
            description="JWT Tool JSON output"
        )
        
        # Commix v1
        self.register_adapter(
            tool_name="commix",
            schema_version="1.x",
            adapter_class=CommixAdapterV1,
            expected_schema={
                "type": "string"
            },
            description="Commix plain text output"
        )
        
        # Semgrep v1
        self.register_adapter(
            tool_name="semgrep",
            schema_version="1.x",
            adapter_class=SemgrepAdapterV1,
            expected_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"}
                }
            },
            description="Semgrep JSON output"
        )
    
    def register_adapter(
        self,
        tool_name: str,
        schema_version: str,
        adapter_class: type,
        expected_schema: Dict,
        description: str
    ) -> None:
        """
        Register a tool adapter.
        
        Args:
            tool_name: Name of the tool
            schema_version: Schema version (e.g., "1.x", "2.0")
            adapter_class: Adapter class (subclass of BaseToolAdapter)
            expected_schema: JSON schema for validation
            description: Human-readable description
        """
        if tool_name not in self.adapters:
            self.adapters[tool_name] = {}
        
        metadata = ToolAdapterMetadata(
            tool_name=tool_name,
            schema_version=schema_version,
            parser_class=adapter_class,
            expected_schema=expected_schema,
            description=description
        )
        
        self.adapters[tool_name][schema_version] = metadata
        
        logger.info(
            f"Registered adapter: {tool_name} v{schema_version} - {description}"
        )
    
    def get_adapter(
        self,
        tool_name: str,
        schema_version: Optional[str] = None
    ) -> BaseToolAdapter:
        """
        Get tool adapter for tool name and version.
        
        Args:
            tool_name: Name of the tool
            schema_version: Schema version (optional, uses latest if not specified)
        
        Returns:
            Tool adapter instance
        
        Raises:
            AdapterNotFound: If no adapter exists for tool/version
        """
        tool_name = tool_name.lower()
        
        if tool_name not in self.adapters:
            raise AdapterNotFound(
                f"No adapter found for tool: {tool_name}"
            )
        
        # If version not specified, use latest (last registered)
        if schema_version is None:
            versions = list(self.adapters[tool_name].keys())
            if not versions:
                raise AdapterNotFound(
                    f"No versions registered for tool: {tool_name}"
                )
            schema_version = versions[-1]
        
        if schema_version not in self.adapters[tool_name]:
            available_versions = list(self.adapters[tool_name].keys())
            raise AdapterNotFound(
                f"No adapter found for {tool_name} v{schema_version}. "
                f"Available versions: {available_versions}"
            )
        
        metadata = self.adapters[tool_name][schema_version]
        return metadata.parser_class()
    
    def parse_with_validation(
        self,
        tool_name: str,
        raw_output: str,
        schema_version: Optional[str] = None
    ) -> List[Dict]:
        """
        Parse tool output with schema validation.
        
        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output
            schema_version: Schema version (optional)
        
        Returns:
            List of parsed findings
        
        Raises:
            AdapterNotFound: If no adapter exists
            SchemaMismatch: If output doesn't match expected schema
        """
        # Get adapter
        adapter = self.get_adapter(tool_name, schema_version)
        
        # Validate schema
        if not adapter.validate_schema(raw_output):
            # Log schema mismatch
            logger.error(
                f"Schema mismatch for {tool_name}: "
                f"output doesn't match expected schema"
            )
            
            raise SchemaMismatch(
                f"Tool output for {tool_name} doesn't match expected schema. "
                f"Tool may have been updated. Please check for new adapter version."
            )
        
        # Parse output
        try:
            findings = adapter.parse(raw_output)
            logger.info(
                f"Successfully parsed {tool_name} output: {len(findings)} findings"
            )
            return findings
        
        except Exception as e:
            logger.error(f"Failed to parse {tool_name} output: {e}")
            raise
    
    def list_adapters(self) -> List[Dict]:
        """
        List all registered adapters.
        
        Returns:
            List of adapter metadata dictionaries
        """
        adapters = []
        
        for tool_name, versions in self.adapters.items():
            for version, metadata in versions.items():
                adapters.append({
                    "tool_name": metadata.tool_name,
                    "schema_version": metadata.schema_version,
                    "description": metadata.description,
                })
        
        return adapters


# Global registry instance
_registry = ToolAdapterRegistry()


def get_registry() -> ToolAdapterRegistry:
    """Get global tool adapter registry."""
    return _registry
