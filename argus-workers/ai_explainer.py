"""
AI Explainer for Argus Pentest Platform.

Generates developer-friendly explanations of vulnerability clusters
using LLM with strict constraints to prevent hallucination and
unauthorized modifications.
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import json
import re
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExplanationResult:
    """Result of AI explanation generation."""
    cluster_id: str
    explanation: str
    model_version: str
    token_count: int
    input_cluster_ids: List[str]
    used_fields: List[str]
    timestamp: datetime


class AIExplainer:
    """
    AI-powered vulnerability explainer with strict constraints.
    
    FORBIDDEN ACTIONS:
    - Re-grouping findings
    - Modifying confidence scores
    - Changing severity levels
    - Inventing new vulnerabilities
    
    ALLOWED ACTIONS:
    - Explain pre-grouped clusters in plain English
    - Describe attacker scenarios
    - Suggest framework-specific fixes
    - Provide verification steps
    """
    
    def __init__(
        self,
        llm_client=None,
        model_version: str = "gpt-4",
        temperature: float = 0.3,
        max_tokens: int = 500,
        db_connection=None
    ):
        """
        Initialize AI explainer.
        
        Args:
            llm_client: LLM client (OpenAI, Anthropic, etc.)
            model_version: Model version to use
            temperature: Temperature for generation (0.3 for factual output)
            max_tokens: Maximum tokens in response (500 limit)
            db_connection: Database connection for storing explanations
        """
        self.llm_client = llm_client
        self.model_version = model_version
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.db = db_connection
    
    async def explain_clusters(
        self,
        clusters: List[Dict]
    ) -> List[ExplanationResult]:
        """
        Generate explanations for pre-grouped vulnerability clusters.
        
        Args:
            clusters: List of pre-grouped vulnerability clusters
        
        Returns:
            List of explanation results
        
        Raises:
            ValueError: If clusters are invalid or contain forbidden modifications
        """
        if not clusters:
            logger.warning("No clusters provided for explanation")
            return []
        
        results = []
        
        for cluster in clusters:
            try:
                # Validate cluster structure
                self._validate_cluster(cluster)
                
                # Sanitize cluster data to prevent prompt injection
                sanitized_cluster = self._sanitize_cluster_data(cluster)
                
                # Build prompt with strict constraints
                prompt = self._build_prompt(sanitized_cluster)
                
                # Generate explanation
                explanation = await self._generate_explanation(prompt)
                
                # Create result
                result = ExplanationResult(
                    cluster_id=cluster["cluster_id"],
                    explanation=explanation,
                    model_version=self.model_version,
                    token_count=len(explanation.split()),  # Approximate
                    input_cluster_ids=[cluster["cluster_id"]],
                    used_fields=list(sanitized_cluster.keys()),
                    timestamp=datetime.now()
                )
                
                # Store explanation and trace
                if self.db:
                    await self._store_explanation(result, sanitized_cluster)
                
                results.append(result)
                
                logger.info(
                    f"Generated explanation for cluster {cluster['cluster_id']}: "
                    f"{len(explanation)} chars"
                )
            
            except Exception as e:
                logger.error(
                    f"Failed to explain cluster {cluster.get('cluster_id', 'unknown')}: {e}"
                )
                continue
        
        return results
    
    def _validate_cluster(self, cluster: Dict) -> None:
        """
        Validate cluster structure.
        
        Args:
            cluster: Vulnerability cluster
        
        Raises:
            ValueError: If cluster is invalid
        """
        required_fields = ["cluster_id", "findings", "severity", "confidence"]
        
        for field in required_fields:
            if field not in cluster:
                raise ValueError(f"Missing required field: {field}")
        
        if not isinstance(cluster["findings"], list):
            raise ValueError("findings must be a list")
        
        if len(cluster["findings"]) == 0:
            raise ValueError("findings list cannot be empty")
    
    def _sanitize_cluster_data(self, cluster: Dict) -> Dict:
        """
        Sanitize cluster data to prevent prompt injection.
        
        Removes or escapes potentially malicious content:
        - Prompt injection attempts
        - Code execution attempts
        - Excessive length fields
        
        Args:
            cluster: Raw cluster data
        
        Returns:
            Sanitized cluster data
        """
        sanitized = {}
        
        # Copy safe fields
        safe_fields = [
            "cluster_id",
            "severity",
            "confidence",
            "vulnerability_type",
            "affected_endpoints",
            "common_patterns"
        ]
        
        for field in safe_fields:
            if field in cluster:
                value = cluster[field]
                
                # Sanitize strings
                if isinstance(value, str):
                    # Remove potential prompt injection patterns
                    value = re.sub(r'(ignore|disregard|forget).*(previous|above|prior)', '', value, flags=re.IGNORECASE)
                    value = re.sub(r'(you are|act as|pretend)', '', value, flags=re.IGNORECASE)
                    
                    # Limit length
                    if len(value) > 500:
                        value = value[:500] + "..."
                
                sanitized[field] = value
        
        # Sanitize findings list
        if "findings" in cluster:
            sanitized_findings = []
            for finding in cluster["findings"][:10]:  # Limit to 10 findings
                sanitized_finding = {
                    "type": finding.get("type", "unknown")[:100],
                    "endpoint": finding.get("endpoint", "unknown")[:200],
                    "severity": finding.get("severity", "unknown"),
                    "confidence": finding.get("confidence", 0.0),
                }
                sanitized_findings.append(sanitized_finding)
            
            sanitized["findings"] = sanitized_findings
        
        return sanitized
    
    def _build_prompt(self, cluster: Dict) -> str:
        """
        Build prompt with strict constraints.
        
        Args:
            cluster: Sanitized cluster data
        
        Returns:
            Prompt string
        """
        findings_summary = "\n".join([
            f"- {f['type']} at {f['endpoint']} (Severity: {f['severity']}, Confidence: {f['confidence']:.0%})"
            for f in cluster.get("findings", [])
        ])
        
        prompt = f"""You are a security expert explaining vulnerabilities to developers.

STRICT RULES:
1. DO NOT modify confidence scores or severity levels
2. DO NOT re-group or reorganize findings
3. DO NOT invent new vulnerabilities not in the input
4. DO NOT suggest changes to the vulnerability classification
5. ONLY explain what is provided

VULNERABILITY CLUSTER:
Cluster ID: {cluster.get('cluster_id')}
Overall Severity: {cluster.get('severity')}
Overall Confidence: {cluster.get('confidence', 0.0):.0%}
Type: {cluster.get('vulnerability_type', 'Unknown')}

FINDINGS:
{findings_summary}

TASK:
Provide a developer-friendly explanation with:
1. Plain English summary (2-3 sentences)
2. Attacker scenario (how this could be exploited)
3. Business impact (what could go wrong)
4. Framework-specific fix guidance (concrete code examples)
5. Verification steps (how to test the fix)

Keep response under 500 tokens. Be factual and specific."""
        
        return prompt
    
    async def _generate_explanation(self, prompt: str) -> str:
        """
        Generate explanation using LLM.
        
        Args:
            prompt: Prompt string
        
        Returns:
            Generated explanation
        """
        if not self.llm_client:
            # Return placeholder if no LLM client configured
            logger.warning("No LLM client configured, returning placeholder")
            return "AI explanation not available (LLM client not configured)"
        
        try:
            # Call LLM API (implementation depends on client)
            # This is a placeholder - actual implementation would use
            # OpenAI, Anthropic, or other LLM API
            
            response = await self.llm_client.chat.completions.create(
                model=self.model_version,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a security expert explaining vulnerabilities to developers. Be factual and specific."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            explanation = response.choices[0].message.content
            
            return explanation
        
        except Exception as e:
            logger.error(f"Failed to generate explanation: {e}")
            return f"Failed to generate explanation: {str(e)}"
    
    async def _store_explanation(
        self,
        result: ExplanationResult,
        cluster: Dict
    ) -> None:
        """
        Store explanation and explainability trace in database.
        
        Args:
            result: Explanation result
            cluster: Sanitized cluster data
        """
        if not self.db:
            return
        
        try:
            from database.repositories.ai_explainability_repository import (
                AIExplainabilityRepository
            )
            
            repo = AIExplainabilityRepository(self.db)
            
            # Store explanation
            await repo.create_explanation(
                cluster_id=result.cluster_id,
                explanation=result.explanation,
                model_version=result.model_version,
                token_count=result.token_count
            )
            
            # Store explainability trace
            trace_data = {
                "input_cluster_ids": result.input_cluster_ids,
                "used_fields": result.used_fields,
                "ignored_fields": [],
                "model_version": result.model_version,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "input_token_count": len(json.dumps(cluster).split()),
                "output_token_count": result.token_count,
                "reasoning_trace": result.explanation[:500],  # First 500 chars
            }
            
            await repo.create_trace(
                cluster_id=result.cluster_id,
                trace_data=trace_data
            )
            
            logger.info(f"Stored explanation and trace for cluster {result.cluster_id}")
        
        except Exception as e:
            logger.error(f"Failed to store explanation: {e}")
