"""
Data models for vulnerability findings
"""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Dict, List, Optional
from enum import Enum
from datetime import datetime


class Severity(str, Enum):
    """Severity levels for findings"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class EvidenceStrength(str, Enum):
    """Evidence strength levels"""
    VERIFIED = "VERIFIED"  # 1.0
    REQUEST_RESPONSE = "REQUEST_RESPONSE"  # 0.9
    PAYLOAD = "PAYLOAD"  # 0.8
    MINIMAL = "MINIMAL"  # 0.6


class VulnerabilityFinding(BaseModel):
    """
    Unified schema for vulnerability findings
    All findings must conform to this schema
    """
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(..., description="Vulnerability type (e.g., SQL_INJECTION, XSS)")
    severity: Severity = Field(..., description="Severity level")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    endpoint: str = Field(..., description="Target endpoint URL")
    evidence: Dict = Field(..., description="Structured evidence")
    source_tool: str = Field(..., description="Tool that discovered the finding")

    repro_steps: Optional[List[str]] = Field(None, description="Reproduction steps")
    cvss_score: Optional[float] = Field(None, ge=0.0, le=10.0, description="CVSS score")
    owasp_category: Optional[str] = Field(None, description="OWASP category")
    cwe_id: Optional[str] = Field(None, description="CWE identifier")
    evidence_strength: Optional[EvidenceStrength] = Field(None, description="Evidence strength level")
    tool_agreement_level: Optional[str] = Field(None, description="Tool agreement level")
    fp_likelihood: Optional[float] = Field(None, ge=0.0, le=1.0, description="False positive likelihood")

    discovered_at: Optional[datetime] = Field(None, description="Discovery timestamp")
    engagement_id: Optional[str] = Field(None, description="Engagement ID")

    @field_validator('evidence')
    @classmethod
    def validate_evidence(cls, v):
        """Ensure evidence has required structure"""
        if not isinstance(v, dict):
            raise ValueError("Evidence must be a dictionary")
        return v

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        """Ensure type is not empty"""
        if not v or not v.strip():
            raise ValueError("Type cannot be empty")
        return v.strip().upper()

    @field_validator('endpoint')
    @classmethod
    def validate_endpoint(cls, v):
        """Ensure endpoint is not empty"""
        if not v or not v.strip():
            raise ValueError("Endpoint cannot be empty")
        return v.strip()


class FindingValidationError(Exception):
    """Raised when finding validation fails"""
    pass
