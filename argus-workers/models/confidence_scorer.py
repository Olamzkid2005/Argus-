"""
Confidence scoring for findings using a weighted heuristic model.
Replaces the naive (tool_agreement * evidence_strength) / (1 + fp_likelihood) formula.
"""
import logging
from feature_flags import is_enabled

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """Weighted confidence scoring model."""

    # Domain-appropriate feature weights (not ML — calibrated heuristic)
    WEIGHTS = {
        "category_fp_rate": 0.20,
        "tool_accuracy": 0.20,
        "evidence_quality": 0.20,
        "multi_tool_agreement": 0.15,
        "context": 0.15,
        "cvss_severity": 0.10,
    }

    # Per-tool accuracy weights (conservative defaults)
    TOOL_ACCURACY = {
        "nuclei": 0.85,
        "dalfox": 0.70,
        "sqlmap": 0.90,
        "semgrep": 0.80,
        "nikto": 0.60,
        "katana": 0.50,
        "gau": 0.40,
        "waybackurls": 0.35,
        "amass": 0.75,
        "subfinder": 0.80,
        "httpx": 0.70,
        "whatweb": 0.85,
        "web_scanner": 0.65,
        "browser_scanner": 0.55,
        "jwt_tool": 0.75,
        "testssl": 0.85,
        "ffuf": 0.50,
        "arjun": 0.60,
        "commix": 0.70,
        "naabu": 0.80,
        "wpscan": 0.85,
    }

    # Base FP rates by vulnerability category
    CATEGORY_FP_RATES = {
        "xss": 0.25,
        "sql_injection": 0.10,
        "lfi": 0.15,
        "rfi": 0.15,
        "rce": 0.10,
        "ssrf": 0.15,
        "open_redirect": 0.30,
        "information_disclosure": 0.35,
        "misconfiguration": 0.25,
        "cve": 0.10,
        "default": 0.20,
    }

    EVIDENCE_QUALITY_SCORES = {
        "verified": 1.0,
        "request_response": 0.9,
        "payload": 0.8,
        "minimal": 0.6,
        "none": 0.3,
    }

    def _extract_features(self, finding: dict, context: dict | None = None) -> dict[str, float]:
        """Extract normalized feature values from a finding."""
        if context is None:
            context = {}

        # Category FP rate (invert: lower FP rate = higher score)
        finding_type = (finding.get("type") or "").lower()
        category_fp = self.CATEGORY_FP_RATES.get(finding_type, self.CATEGORY_FP_RATES["default"])
        category_score = 1.0 - category_fp

        # Tool accuracy
        source_tool = finding.get("source_tool") or finding.get("tool") or "unknown"
        tool_acc = self.TOOL_ACCURACY.get(source_tool, 0.50)

        # Evidence quality
        evidence = finding.get("evidence", {})
        if isinstance(evidence, dict):
            evidence_type = evidence.get("type", "none")
        else:
            evidence_type = "minimal" if evidence else "none"
        evidence_score = self.EVIDENCE_QUALITY_SCORES.get(
            evidence_type, self.EVIDENCE_QUALITY_SCORES["none"]
        )
        # Boost score if there's actual content in evidence
        if isinstance(evidence, dict) and any(v for v in evidence.values() if v):
            evidence_score = max(evidence_score, 0.7)

        # Multi-tool agreement
        tool_agreement_raw = finding.get("tool_agreement_level", 1.0)
        if isinstance(tool_agreement_raw, str):
            agreement_map = {"high": 1.0, "medium": 0.85, "single_tool": 0.7, "low": 0.5}
            tool_agreement = agreement_map.get(tool_agreement_raw.lower(), 0.7)
        else:
            tool_agreement = float(tool_agreement_raw)
        multi_tool_score = min(1.0, tool_agreement * 0.33)

        # Context score
        is_public = context.get("is_public_endpoint", True)
        is_authenticated = context.get("requires_auth", False)
        if is_authenticated:
            context_score = 0.7
        elif not is_public:
            context_score = 0.8
        else:
            context_score = 0.9

        # CVSS severity
        cvss = finding.get("cvss_score") or 0
        cvss_score = min(1.0, cvss / 10.0) if isinstance(cvss, (int, float)) else 0.5

        return {
            "category_fp_rate": category_score,
            "tool_accuracy": tool_acc,
            "evidence_quality": evidence_score,
            "multi_tool_agreement": multi_tool_score,
            "context": context_score,
            "cvss_severity": cvss_score,
        }

    def score(self, finding: dict, context: dict | None = None) -> float:
        """Calculate weighted confidence score."""
        if not is_enabled("ML_CONFIDENCE"):
            return self._legacy_score(finding)

        features = self._extract_features(finding, context)
        score_value = sum(self.WEIGHTS[k] * v for k, v in features.items())
        return max(0.0, min(1.0, score_value))

    def _legacy_score(self, finding: dict) -> float:
        """Legacy naive confidence formula."""
        tool_agreement_raw = finding.get("tool_agreement_level", 0.7)
        if isinstance(tool_agreement_raw, str):
            agreement_map = {"high": 1.0, "medium": 0.85, "single_tool": 0.7, "low": 0.5}
            tool_agreement = agreement_map.get(tool_agreement_raw.lower(), 0.7)
        else:
            tool_agreement = float(tool_agreement_raw)
        evidence_strength = float(finding.get("evidence_strength", 0.7) or 0.7)
        fp_likelihood = float(finding.get("fp_likelihood", 0.2) or 0.2)
        confidence = (tool_agreement * evidence_strength) / (1 + fp_likelihood)
        return max(0.0, min(1.0, confidence))
