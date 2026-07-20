"""
Data models for vulnerability findings
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from exceptions import FindingValidationError as FindingValidationError  # re-exported
from tool_core._compat import StrEnum


class Severity(StrEnum):
    """Severity levels for findings"""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class EvidenceStrength(StrEnum):
    """Evidence strength levels"""

    NONE = "NONE"  # 0.0
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
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )
    endpoint: str = Field(..., description="Target endpoint URL")
    evidence: dict = Field(..., description="Structured evidence")
    source_tool: str = Field(..., description="Tool that discovered the finding")

    repro_steps: list[str] | None = Field(None, description="Reproduction steps")
    cvss_score: float | None = Field(None, ge=0.0, le=10.0, description="CVSS score")
    owasp_category: str | None = Field(None, description="OWASP category")
    cwe_id: str | None = Field(None, description="CWE identifier")
    evidence_strength: EvidenceStrength | None = Field(
        None, description="Evidence strength level"
    )
    tool_agreement_level: str | None = Field(None, description="Tool agreement level")
    fp_likelihood: float | None = Field(
        None, ge=0.0, le=1.0, description="False positive likelihood"
    )

    discovered_at: datetime | None = Field(None, description="Discovery timestamp")
    engagement_id: str | None = Field(None, description="Engagement ID")

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, v):
        """Ensure evidence has required structure — coerce strings/lists to dicts"""
        if isinstance(v, str):
            try:
                import json

                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {"raw": v}
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            return {"items": v}
        if v is None:
            return {}
        return {"raw": str(v)}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        """Ensure type is not empty — default to UNKNOWN"""
        if not v or not str(v).strip():
            return "UNKNOWN"
        return str(v).strip().upper()

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v):
        """Ensure endpoint is not empty — default to UNKNOWN"""
        if not v or not str(v).strip():
            return "UNKNOWN"
        return str(v).strip()


