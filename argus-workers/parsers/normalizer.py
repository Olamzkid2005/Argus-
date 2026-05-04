"""
Normalizer - Enforces VulnerabilityFinding schema and normalizes data
"""

from pydantic import ValidationError

from models.finding import (
    EvidenceStrength,
    FindingValidationError,
    Severity,
    VulnerabilityFinding,
)


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
        # Command Injection / RCE
        "command injection": "COMMAND_INJECTION",
        "os command injection": "COMMAND_INJECTION",
        "rce": "REMOTE_CODE_EXECUTION",
        # Path Traversal
        "path traversal": "PATH_TRAVERSAL",
        "directory traversal": "PATH_TRAVERSAL",
        "lfi": "PATH_TRAVERSAL",
        # XXE
        "xxe": "XML_EXTERNAL_ENTITY",
        "xml external entity": "XML_EXTERNAL_ENTITY",
        # CSRF
        "csrf": "CSRF",
        "cross-site request forgery": "CSRF",
        # Session Hijacking
        "session hijacking": "SESSION_HIJACKING",
        "session fixation": "SESSION_HIJACKING",
        # Race Condition
        "race condition": "RACE_CONDITION",
        # Business Logic
        "business logic": "BUSINESS_LOGIC",
        "logic flaw": "BUSINESS_LOGIC",
        # Default
        "http_endpoint": "HTTP_ENDPOINT",
        "directory_found": "DIRECTORY_FOUND",
        # New tool types
        "crawled_endpoint": "CRAWLED_ENDPOINT",
        "known_url": "KNOWN_URL",
        "historical_url": "HISTORICAL_URL",
        "parameter_discovery": "PARAMETER_DISCOVERY",
        "code_vulnerability": "CODE_VULNERABILITY",
        # Web Scanner types
        "missing_security_headers": "SECURITY_MISCONFIGURATION",
        "missing_csp": "SECURITY_MISCONFIGURATION",
        "weak_csp": "SECURITY_MISCONFIGURATION",
        "insecure_cookie": "INSECURE_COOKIE",
        "wildcard_cors": "CORS_MISCONFIGURATION",
        "reflected_origin_cors": "CORS_MISCONFIGURATION",
        "exposed_sensitive_file": "INFORMATION_DISCLOSURE",
        "exposed_secret": "EXPOSED_SECRET",
        "open_redirect": "OPEN_REDIRECT",
        "host_header_injection": "HOST_HEADER_INJECTION",
        "http_verb_tampering": "HTTP_VERB_TAMPERING",
        "exposed_debug_endpoint": "EXPOSED_DEBUG_ENDPOINT",
        "default_credentials": "DEFAULT_CREDENTIALS",
        "mass_assignment": "MASS_ASSIGNMENT",
        "reflected_xss": "XSS",
        "ssti": "SERVER_SIDE_TEMPLATE_INJECTION",
        # pip-audit
        "dependency_vulnerability": "DEPENDENCY_VULNERABILITY",
        "pip_audit": "DEPENDENCY_VULNERABILITY",
        # bandit
        "bandit_*": "CODE_VULNERABILITY",
        # subfinder
        "subdomain_discovery": "SUBDOMAIN_DISCOVERY",
        "subdomain_permutation": "SUBDOMAIN_PERMUTATION",
    }

    # CWE to vulnerability type mappings
    CWE_TYPE_MAPPINGS = {
        # CWE-78: OS Command Injection (RCE)
        "CWE-78": "REMOTE_CODE_EXECUTION",
        "CWE-74": "REMOTE_CODE_EXECUTION",
        "CWE-94": "CODE_INJECTION",
        # CWE-352: CSRF
        "CWE-352": "CSRF",
        # CWE-79: XSS (stored/reflected)
        "CWE-79": "XSS",
        # CWE-86: DOM XSS
        "CWE-86": "DOM_XSS",
        # CWE-639: IDOR
        "CWE-639": "IDOR",
        # CWE-611: XXE
        "CWE-611": "XML_EXTERNAL_ENTITY",
        # CWE-200: Information Disclosure
        "CWE-200": "INFORMATION_DISCLOSURE",
        "CWE-319": "CLEARTEXT_TRANSMISSION",
        # CWE-462: Race Condition
        "CWE-462": "RACE_CONDITION",
        # CWE-367: Race Condition (TOCTOU)
        "CWE-367": "RACE_CONDITION",
        # CWE-287: Authentication Issues
        "CWE-287": "BROKEN_AUTHENTICATION",
        # CWE-306: Missing Authentication
        "CWE-306": "MISSING_AUTHENTICATION",
        # CWE-22: Path Traversal
        "CWE-22": "PATH_TRAVERSAL",
        # CWE-89: SQL Injection
        "CWE-89": "SQL_INJECTION",
        # CWE-918: SSRF
        "CWE-918": "SSRF",
        # CWE-250: Unnecessary Privileges
        "CWE-250": "PRIVILEGE_ESCALATION",
        # CWE-915: Improperly Controlled Modification
        "CWE-915": "MASS_ASSIGNMENT",
        # CWE-697: Incorrect Comparison
        "CWE-697": "BUSINESS_LOGIC",
        # CWE-353: Missing Integrity Check
        "CWE-353": "MISSING_INTEGRITY_CHECK",
    }

    # OWASP to vulnerability type mappings
    OWASP_TYPE_MAPPINGS = {
        "A01:2021-Broken Access Control": "IDOR",
        "A02:2021-Cryptographic Failures": "WEAK_CRYPTOGRAPHY",
        "A03:2021-Injection": "SQL_INJECTION",
        "A04:2021-Insecure Design": "BUSINESS_LOGIC",
        "A05:2021-Security Misconfiguration": "SECURITY_MISCONFIGURATION",
        "A06:2021-Vulnerable and Outdated Components": "VULNERABLE_DEPENDENCY",
        "A07:2021-Identification and Authentication Failures": "BROKEN_AUTHENTICATION",
        "A08:2021-Software and Data Integrity Failures": "INTEGRITY_FAILURE",
        "A09:2021-Security Logging and Monitoring Failures": "INSUFFICIENT_LOGGING",
        "A10:2021-Server-Side Request Forgery (SSRF)": "SSRF",
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
        "web_scanner": 0.15,
        "pip_audit": 0.10,
        "bandit": 0.15,
        "nmap": 0.10,
        "subfinder": 0.10,
        "alterx": 0.30,
    }

    def normalize(
        self, raw_finding: dict, source_tool: str, context: dict | None = None
    ) -> VulnerabilityFinding:
        """
        Convert raw tool output to VulnerabilityFinding

        Args:
            raw_finding: Raw finding dictionary from parser
            source_tool: Name of the source tool
            context: Optional context for severity adjustment (endpoint exposure)

        Returns:
            Validated VulnerabilityFinding

        Raises:
            FindingValidationError: If validation fails
        """
        try:
            # Normalize type (pass full raw_finding for CWE extraction)
            normalized_type = self._normalize_type(
                raw_finding.get("type", "UNKNOWN"), source_tool, raw_finding
            )

            # Normalize severity with context-aware adjustment
            if context:
                normalized_severity = Severity(
                    self.normalize_severity_with_context(
                        raw_finding.get("severity", "INFO"), context
                    )
                )
            else:
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
            raise FindingValidationError(f"Validation failed: {e}") from e
        except Exception as e:
            raise FindingValidationError(f"Normalization failed: {e}") from e

    def _normalize_type(
        self, raw_type: str, source_tool: str, raw_finding: dict = None
    ) -> str:
        """
        Normalize vulnerability type names

        Args:
            raw_type: Raw type from tool
            source_tool: Source tool name
            raw_finding: Full raw finding (for CWE extraction)

        Returns:
            Standardized type name
        """
        raw_type_lower = raw_type.lower().strip()

        # Check mappings based on raw type first
        if raw_type_lower in self.TYPE_MAPPINGS:
            return self.TYPE_MAPPINGS[raw_type_lower]

        # If we have CWE info in evidence, use it to determine type
        if raw_finding:
            evidence = raw_finding.get("evidence", {})

            # Extract CWE from evidence (Semgrep puts it here)
            cwe = evidence.get("cwe", "")
            if cwe:
                # Handle formats like "CWE-78", "CWE:78", "78"
                cwe = cwe.upper()
                if not cwe.startswith("CWE-"):
                    cwe = f"CWE-{cwe}"

                # Also try without prefix
                cwe_key = cwe.replace("CWE-", "")
                if cwe_key in self.CWE_TYPE_MAPPINGS:
                    return self.CWE_TYPE_MAPPINGS[cwe_key]
                if cwe in self.CWE_TYPE_MAPPINGS:
                    return self.CWE_TYPE_MAPPINGS[cwe]

            # Also check OWASP category
            owasp = evidence.get("owasp", "")
            if owasp and owasp in self.OWASP_TYPE_MAPPINGS:
                return self.OWASP_TYPE_MAPPINGS[owasp]

            # Try to extract from metadata or other fields
            metadata = raw_finding.get("metadata", {})
            if metadata:
                cwe = metadata.get("cwe", "")
                if cwe:
                    cwe = cwe.upper()
                    if cwe in self.CWE_TYPE_MAPPINGS:
                        return self.CWE_TYPE_MAPPINGS[cwe]

                owasp = metadata.get("owasp", "")
                if owasp and owasp in self.OWASP_TYPE_MAPPINGS:
                    return self.OWASP_TYPE_MAPPINGS[owasp]

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

    def normalize_severity_with_context(
        self, raw_severity: str, context: dict | None = None
    ) -> str:
        """
        Normalize severity with context-aware adjustments.

        Adjusts severity based on endpoint exposure:
        - Internal/admin endpoints: CRITICAL → HIGH, HIGH → MEDIUM
        - Public API endpoints: MEDIUM → HIGH
        - Authenticated-only: CRITICAL → HIGH (still serious, but requires auth)
        """
        if not context:
            return self._normalize_severity(raw_severity).value

        base_severity = self._normalize_severity(raw_severity)
        severity_order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

        if base_severity.value not in severity_order:
            return base_severity.value

        current_idx = severity_order.index(base_severity.value)

        is_internal = context.get("is_internal_endpoint", False)
        is_admin = context.get("is_admin_panel", False)
        is_public_api = context.get("is_public_api", False)
        requires_auth = context.get("requires_auth", False)

        if is_internal or is_admin:
            if current_idx >= 4:
                current_idx = 3
            elif current_idx >= 3:
                current_idx = 2

        if requires_auth:
            if current_idx >= 4:
                current_idx = 3

        if is_public_api:
            if current_idx == 2:
                current_idx = 3

        return severity_order[current_idx]

    def _structure_evidence(self, raw_evidence: dict) -> dict:
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

    def _calculate_confidence(self, raw_finding: dict, source_tool: str) -> float:
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

    def _assess_evidence_strength(self, raw_finding: dict) -> EvidenceStrength:
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

    def _get_evidence_strength_score(self, raw_finding: dict) -> float:
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

    def _estimate_fp_likelihood(self, raw_finding: dict, source_tool: str) -> float:
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

    def normalize_batch(
        self, raw_findings: list[dict], source_tool: str
    ) -> list[VulnerabilityFinding]:
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
