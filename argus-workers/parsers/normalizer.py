"""
Normalizer - Enforces VulnerabilityFinding schema and normalizes data
"""
from typing import Dict, List
from models.finding import VulnerabilityFinding, Severity, EvidenceStrength, FindingValidationError
from pydantic import ValidationError


class FindingNormalizer:
    """
    Normalizes raw tool findings to VulnerabilityFinding schema
    """
    
    # Type name mappings (tool-specific → standardized)
    TYPE_MAPPINGS = {
        # SQL Injection variants
        "sqli": "SQL_INJECTION",
        "sql injection": "SQL_INJECTION",
        "sql-injection": "SQL_INJECTION",
        "blind sqli": "SQL_INJECTION",
        "time-based sqli": "SQL_INJECTION",
        
        # XSS variants
        "xss": "XSS",
        "cross-site scripting": "XSS",
        "reflected xss": "XSS",
        "stored xss": "XSS",
        "dom xss": "XSS",
        
        # IDOR variants
        "idor": "IDOR",
        "insecure direct object reference": "IDOR",
        
        # Authentication/Authorization
        "broken authentication": "BROKEN_AUTHENTICATION",
        "broken authorization": "BROKEN_AUTHORIZATION",
        "missing authentication": "MISSING_AUTHENTICATION",
        
        # Information Disclosure
        "info disclosure": "INFORMATION_DISCLOSURE",
        "information disclosure": "INFORMATION_DISCLOSURE",
        "sensitive data exposure": "INFORMATION_DISCLOSURE",
        
        # SSRF
        "ssrf": "SSRF",
        "server-side request forgery": "SSRF",
        
        # Command Injection
        "command injection": "COMMAND_INJECTION",
        "os command injection": "COMMAND_INJECTION",
        
        # Path Traversal
        "path traversal": "PATH_TRAVERSAL",
        "directory traversal": "PATH_TRAVERSAL",
        "lfi": "PATH_TRAVERSAL",
        
        # Default
        "http_endpoint": "HTTP_ENDPOINT",
        "directory_found": "DIRECTORY_FOUND",
        
        # New tool types
        "crawled_endpoint": "CRAWLED_ENDPOINT",
        "known_url": "KNOWN_URL",
        "historical_url": "HISTORICAL_URL",
        "parameter_discovery": "PARAMETER_DISCOVERY",
        "code_vulnerability": "CODE_VULNERABILITY",
    }
    
    # Severity mappings (tool-specific → Severity enum)
    SEVERITY_MAPPINGS = {
        "critical": Severity.CRITICAL,
        "high": Severity.HIGH,
        "medium": Severity.MEDIUM,
        "low": Severity.LOW,
        "info": Severity.INFO,
        "informational": Severity.INFO,
        "unknown": Severity.INFO,
    }
    
    # Tool-specific false positive rates
    TOOL_FP_RATES = {
        "nuclei": 0.15,
        "sqlmap": 0.10,
        "burp": 0.05,
        "httpx": 0.30,
        "ffuf": 0.40,
        # New tools
        "katana": 0.10,
        "gau": 0.25,
        "waybackurls": 0.30,
        "arjun": 0.10,
        "dalfox": 0.10,
        "jwt_tool": 0.08,
        "commix": 0.05,
        "semgrep": 0.12,
    }
    
    def normalize(self, raw_finding: Dict, source_tool: str) -> VulnerabilityFinding:
        """
        Convert raw tool output to VulnerabilityFinding
        
        Args:
            raw_finding: Raw finding dictionary from parser
            source_tool: Name of the source tool
            
        Returns:
            Validated VulnerabilityFinding
            
        Raises:
            FindingValidationError: If validation fails
        """
        try:
            # Normalize type
            normalized_type = self._normalize_type(
                raw_finding.get("type", "UNKNOWN"),
                source_tool
            )
            
            # Normalize severity
            normalized_severity = self._normalize_severity(
                raw_finding.get("severity", "INFO")
            )
            
            # Calculate confidence if not provided
            confidence = raw_finding.get("confidence")
            if confidence is None:
                confidence = self._calculate_confidence(raw_finding, source_tool)
            
            # Structure evidence consistently
            evidence = self._structure_evidence(raw_finding.get("evidence", {}))
            
            # Assess evidence strength
            evidence_strength = self._assess_evidence_strength(raw_finding)
            
            # Estimate false positive likelihood
            fp_likelihood = self._estimate_fp_likelihood(raw_finding, source_tool)
            
            # Create VulnerabilityFinding
            finding = VulnerabilityFinding(
                type=normalized_type,
                severity=normalized_severity,
                confidence=confidence,
                endpoint=raw_finding.get("endpoint", ""),
                evidence=evidence,
                source_tool=source_tool,
                evidence_strength=evidence_strength,
                fp_likelihood=fp_likelihood,
            )
            
            return finding
            
        except ValidationError as e:
            raise FindingValidationError(f"Validation failed: {e}")
        except Exception as e:
            raise FindingValidationError(f"Normalization failed: {e}")
    
    def _normalize_type(self, raw_type: str, source_tool: str) -> str:
        """
        Normalize vulnerability type names
        
        Args:
            raw_type: Raw type from tool
            source_tool: Source tool name
            
        Returns:
            Standardized type name
        """
        raw_type_lower = raw_type.lower().strip()
        
        # Check mappings
        if raw_type_lower in self.TYPE_MAPPINGS:
            return self.TYPE_MAPPINGS[raw_type_lower]
        
        # Return uppercase version if no mapping found
        return raw_type.upper().replace(" ", "_")
    
    def _normalize_severity(self, raw_severity: str) -> Severity:
        """
        Normalize severity to enum
        
        Args:
            raw_severity: Raw severity from tool
            
        Returns:
            Severity enum value
        """
        raw_severity_lower = raw_severity.lower().strip()
        
        return self.SEVERITY_MAPPINGS.get(raw_severity_lower, Severity.INFO)
    
    def _structure_evidence(self, raw_evidence: Dict) -> Dict:
        """
        Structure evidence in consistent format
        
        Args:
            raw_evidence: Raw evidence dictionary
            
        Returns:
            Structured evidence with standard fields
        """
        structured = {
            "request": raw_evidence.get("request", ""),
            "response": raw_evidence.get("response", ""),
            "payload": raw_evidence.get("payload", ""),
            "matched_pattern": raw_evidence.get("matched_pattern", ""),
        }
        
        # Include any additional fields
        for key, value in raw_evidence.items():
            if key not in structured:
                structured[key] = value
        
        return structured
    
    def _calculate_confidence(self, raw_finding: Dict, source_tool: str) -> float:
        """
        Calculate confidence score
        
        Formula: (tool_agreement × evidence_strength) / (1 + fp_likelihood)
        
        Args:
            raw_finding: Raw finding dictionary
            source_tool: Source tool name
            
        Returns:
            Confidence score (0.0-1.0)
        """
        # For single tool, tool_agreement = 0.7
        tool_agreement = 0.7
        
        # Assess evidence strength
        evidence_strength = self._get_evidence_strength_score(raw_finding)
        
        # Get FP likelihood
        fp_likelihood = self._estimate_fp_likelihood(raw_finding, source_tool)
        
        # Calculate confidence
        confidence = (tool_agreement * evidence_strength) / (1 + fp_likelihood)
        
        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, confidence))
    
    def _assess_evidence_strength(self, raw_finding: Dict) -> EvidenceStrength:
        """
        Assess evidence strength level
        
        Args:
            raw_finding: Raw finding dictionary
            
        Returns:
            EvidenceStrength enum value
        """
        evidence = raw_finding.get("evidence", {})
        
        # Check for verified exploit
        if evidence.get("verified") or raw_finding.get("verified"):
            return EvidenceStrength.VERIFIED
        
        # Check for request/response pair
        if evidence.get("request") and evidence.get("response"):
            return EvidenceStrength.REQUEST_RESPONSE
        
        # Check for payload
        if evidence.get("payload"):
            return EvidenceStrength.PAYLOAD
        
        # Minimal evidence
        return EvidenceStrength.MINIMAL
    
    def _get_evidence_strength_score(self, raw_finding: Dict) -> float:
        """
        Get numeric evidence strength score
        
        Args:
            raw_finding: Raw finding dictionary
            
        Returns:
            Evidence strength score (0.6-1.0)
        """
        strength = self._assess_evidence_strength(raw_finding)
        
        scores = {
            EvidenceStrength.VERIFIED: 1.0,
            EvidenceStrength.REQUEST_RESPONSE: 0.9,
            EvidenceStrength.PAYLOAD: 0.8,
            EvidenceStrength.MINIMAL: 0.6,
        }
        
        return scores.get(strength, 0.6)
    
    def _estimate_fp_likelihood(self, raw_finding: Dict, source_tool: str) -> float:
        """
        Estimate false positive likelihood
        
        Args:
            raw_finding: Raw finding dictionary
            source_tool: Source tool name
            
        Returns:
            FP likelihood (0.0-1.0)
        """
        # Get tool-specific FP rate
        base_fp_rate = self.TOOL_FP_RATES.get(source_tool.lower(), 0.20)
        
        # Reduce by 90% if verified
        if raw_finding.get("verified"):
            base_fp_rate *= 0.1
        
        return base_fp_rate
    
    def normalize_batch(self, raw_findings: List[Dict], source_tool: str) -> List[VulnerabilityFinding]:
        """
        Normalize a batch of findings
        
        Args:
            raw_findings: List of raw findings
            source_tool: Source tool name
            
        Returns:
            List of validated findings (skips invalid ones)
        """
        normalized = []
        
        for raw_finding in raw_findings:
            try:
                finding = self.normalize(raw_finding, source_tool)
                normalized.append(finding)
            except FindingValidationError as e:
                # Log validation error but continue
                print(f"Skipping invalid finding: {e}")
                continue
        
        return normalized
