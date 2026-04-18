"""
Intelligence Engine - THE ONLY decision-maker
Analyzes findings and generates recommended actions

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 20.6, 21.1, 21.2
"""
from typing import Dict, List, Optional
from collections import defaultdict
import time
import os

from tracing import get_trace_id, StructuredLogger, ExecutionSpan


class IntelligenceEngine:
    """
    Decision-making core that analyzes findings and generates actions.
    Uses ONLY frozen snapshot data, never live DB reads.
    """
    
    def __init__(self, connection_string: str = None):
        """
        Initialize Intelligence Engine.
        
        Args:
            connection_string: Database connection string for tracing
        """
        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)
    
    def evaluate(self, snapshot: Dict) -> Dict:
        """
        Evaluate snapshot and generate actions.
        Uses ONLY frozen snapshot data, never live DB reads.
        
        Args:
            snapshot: Immutable snapshot containing:
                - findings: List of findings
                - attack_graph: Attack graph data
                - loop_budget: Current loop budget status
                - engagement_state: Current engagement state
                
        Returns:
            Dictionary with:
                - scored_findings: Findings with updated confidence scores
                - actions: List of recommended actions
                - reasoning: Explanation of decisions
        """
        findings = snapshot.get("findings", [])
        loop_budget = snapshot.get("loop_budget", {})
        
        # Execute with span tracing
        with self.span_recorder.span(
            ExecutionSpan.SPAN_INTELLIGENCE_EVALUATION,
            {"findings_count": len(findings)}
        ):
            # Assign confidence scores
            scored_findings = self.assign_confidence_scores(findings)
            
            # Generate actions based on intelligence
            actions = self.generate_actions(scored_findings, snapshot)
            
            # Generate reasoning
            reasoning = self._generate_reasoning(scored_findings, actions)
            
            # Log intelligence decision
            self.logger.log_intelligence_decision(
                actions=actions,
                findings_analyzed=len(findings),
                reasoning=reasoning
            )
            
            return {
                "scored_findings": scored_findings,
                "actions": actions,
                "reasoning": reasoning,
                "trace_id": get_trace_id(),
            }
    
    def assign_confidence_scores(self, findings: List[Dict]) -> List[Dict]:
        """
        Calculate confidence using formula:
        confidence = (tool_agreement × evidence_strength) / (1 + fp_likelihood)
        
        Args:
            findings: List of findings
            
        Returns:
            Findings with updated confidence scores
        """
        # Group findings by endpoint and type to detect tool agreement
        finding_groups = defaultdict(list)
        
        for finding in findings:
            key = (finding.get("endpoint"), finding.get("type"))
            finding_groups[key].append(finding)
        
        scored_findings = []
        
        for finding in findings:
            key = (finding.get("endpoint"), finding.get("type"))
            group = finding_groups[key]
            
            # Calculate tool agreement
            tool_agreement = self._calculate_tool_agreement(group)
            
            # Get evidence strength
            evidence_strength = self._get_evidence_strength(finding)
            
            # Get FP likelihood
            fp_likelihood = finding.get("fp_likelihood", 0.2)
            
            # Calculate confidence
            confidence = (tool_agreement * evidence_strength) / (1 + fp_likelihood)
            confidence = max(0.0, min(1.0, confidence))
            
            # Update finding
            scored_finding = finding.copy()
            scored_finding["confidence"] = confidence
            scored_finding["tool_agreement_level"] = self._get_agreement_level(len(group))
            
            scored_findings.append(scored_finding)
        
        return scored_findings
    
    def _calculate_tool_agreement(self, findings_group: List[Dict]) -> float:
        """
        Calculate tool agreement score
        
        Args:
            findings_group: Group of findings for same endpoint/type
            
        Returns:
            Tool agreement score
        """
        num_tools = len(set(f.get("source_tool") for f in findings_group))
        
        if num_tools >= 3:
            return 1.0
        elif num_tools == 2:
            return 0.85
        else:
            return 0.7
    
    def _get_agreement_level(self, num_tools: int) -> str:
        """Get agreement level string"""
        if num_tools >= 3:
            return "high"
        elif num_tools == 2:
            return "medium"
        else:
            return "single_tool"
    
    def _get_evidence_strength(self, finding: Dict) -> float:
        """
        Get evidence strength score
        
        Args:
            finding: Finding dictionary
            
        Returns:
            Evidence strength score (0.6-1.0)
        """
        evidence_strength = finding.get("evidence_strength", "MINIMAL")
        
        scores = {
            "VERIFIED": 1.0,
            "REQUEST_RESPONSE": 0.9,
            "PAYLOAD": 0.8,
            "MINIMAL": 0.6,
        }
        
        return scores.get(evidence_strength, 0.6)
    
    def generate_actions(self, scored_findings: List[Dict], context: Dict) -> List[Dict]:
        """
        Generate recommended actions based on intelligence
        
        Args:
            scored_findings: Findings with confidence scores
            context: Snapshot context
            
        Returns:
            List of recommended actions
        """
        actions = []
        
        # Pattern: Low coverage detected
        if self.detect_low_coverage(scored_findings):
            actions.append({
                "type": "recon_expand",
                "scope": self.suggest_new_targets(scored_findings),
                "reason": "low_coverage_detected",
                "description": "Insufficient endpoint coverage detected. Expanding reconnaissance to discover more attack surface.",
            })
        
        # Pattern: High-value targets found
        if self.detect_high_value_targets(scored_findings):
            actions.append({
                "type": "deep_scan",
                "targets": self.get_priority_endpoints(scored_findings),
                "reason": "high_value_targets_identified",
                "description": "High-value targets with potential vulnerabilities identified. Performing deep scan.",
            })
        
        # Pattern: Weak authentication signals
        if self.detect_weak_auth_signals(scored_findings):
            actions.append({
                "type": "auth_focused_scan",
                "endpoints": self.get_auth_endpoints(scored_findings),
                "reason": "weak_auth_signals",
                "description": "Weak authentication signals detected. Focusing on authentication mechanisms.",
            })
        
        return actions
    
    def detect_low_coverage(self, findings: List[Dict]) -> bool:
        """
        Detect if coverage is insufficient
        
        Args:
            findings: List of findings
            
        Returns:
            True if low coverage detected
        """
        # Count unique endpoints
        endpoints = set(f.get("endpoint") for f in findings)
        
        # Low coverage if fewer than 5 unique endpoints
        return len(endpoints) < 5
    
    def suggest_new_targets(self, findings: List[Dict]) -> List[str]:
        """
        Suggest new targets for reconnaissance
        
        Args:
            findings: List of findings
            
        Returns:
            List of suggested targets
        """
        # Extract domains from existing findings
        domains = set()
        for finding in findings:
            endpoint = finding.get("endpoint", "")
            if "://" in endpoint:
                domain = endpoint.split("://")[1].split("/")[0]
                domains.add(domain)
        
        # Suggest common subdomains
        suggestions = []
        for domain in domains:
            suggestions.extend([
                f"https://api.{domain}",
                f"https://admin.{domain}",
                f"https://dev.{domain}",
            ])
        
        return suggestions[:5]  # Limit to 5 suggestions
    
    def detect_high_value_targets(self, findings: List[Dict]) -> bool:
        """
        Detect high-value targets for deep scanning
        
        Args:
            findings: List of findings
            
        Returns:
            True if high-value targets found
        """
        # High-value if any CRITICAL or HIGH severity findings
        for finding in findings:
            severity = finding.get("severity", "INFO")
            if severity in ["CRITICAL", "HIGH"]:
                return True
        
        return False
    
    def get_priority_endpoints(self, findings: List[Dict]) -> List[str]:
        """
        Get priority endpoints for deep scanning
        
        Args:
            findings: List of findings
            
        Returns:
            List of priority endpoints
        """
        priority_endpoints = []
        
        for finding in findings:
            severity = finding.get("severity", "INFO")
            if severity in ["CRITICAL", "HIGH"]:
                endpoint = finding.get("endpoint")
                if endpoint and endpoint not in priority_endpoints:
                    priority_endpoints.append(endpoint)
        
        return priority_endpoints[:10]  # Limit to top 10
    
    def detect_weak_auth_signals(self, findings: List[Dict]) -> bool:
        """
        Detect weak authentication signals
        
        Args:
            findings: List of findings
            
        Returns:
            True if weak auth signals detected
        """
        auth_keywords = [
            "authentication",
            "authorization",
            "login",
            "auth",
            "session",
            "token",
            "jwt",
        ]
        
        for finding in findings:
            finding_type = finding.get("type", "").lower()
            endpoint = finding.get("endpoint", "").lower()
            
            # Check if finding relates to authentication
            for keyword in auth_keywords:
                if keyword in finding_type or keyword in endpoint:
                    return True
        
        return False
    
    def get_auth_endpoints(self, findings: List[Dict]) -> List[str]:
        """
        Get authentication-related endpoints
        
        Args:
            findings: List of findings
            
        Returns:
            List of auth endpoints
        """
        auth_keywords = [
            "authentication",
            "authorization",
            "login",
            "auth",
            "session",
            "token",
            "jwt",
        ]
        
        auth_endpoints = []
        
        for finding in findings:
            endpoint = finding.get("endpoint", "").lower()
            
            for keyword in auth_keywords:
                if keyword in endpoint and endpoint not in auth_endpoints:
                    auth_endpoints.append(finding.get("endpoint"))
                    break
        
        return auth_endpoints[:10]  # Limit to top 10
    
    def _generate_reasoning(self, findings: List[Dict], actions: List[Dict]) -> str:
        """
        Generate reasoning explanation
        
        Args:
            findings: Scored findings
            actions: Generated actions
            
        Returns:
            Reasoning text
        """
        reasoning_parts = []
        
        reasoning_parts.append(f"Analyzed {len(findings)} findings.")
        
        # Count by severity
        severity_counts = defaultdict(int)
        for finding in findings:
            severity_counts[finding.get("severity", "INFO")] += 1
        
        reasoning_parts.append(
            f"Severity distribution: "
            f"Critical={severity_counts['CRITICAL']}, "
            f"High={severity_counts['HIGH']}, "
            f"Medium={severity_counts['MEDIUM']}, "
            f"Low={severity_counts['LOW']}, "
            f"Info={severity_counts['INFO']}"
        )
        
        reasoning_parts.append(f"Generated {len(actions)} recommended actions.")
        
        for action in actions:
            reasoning_parts.append(f"- {action['type']}: {action['description']}")
        
        return " ".join(reasoning_parts)
