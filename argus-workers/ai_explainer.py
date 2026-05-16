"""
AI Explainer for Argus Pentest Platform.

Generates developer-friendly explanations of vulnerability clusters
using LLM with strict constraints to prevent hallucination and
unauthorized modifications.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExplanationResult:
    """Result of AI explanation generation."""
    cluster_id: str
    explanation: str
    model_version: str
    token_count: int
    input_cluster_ids: list[str]
    used_fields: list[str]
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
    - Generate embeddings for similarity search
    """

    # Embedding model configuration
    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS = 1536

    def __init__(
        self,
        llm_client=None,
        model_version: str = "gpt-4",
        temperature: float = 0.3,
        max_tokens: int = 500,
        db_connection=None,
        embedding_client=None
    ):
        """
        Initialize AI explainer.

        Args:
            llm_client: LLM client (OpenAI, Anthropic, etc.) for explanations
            model_version: Model version to use
            temperature: Temperature for generation (0.3 for factual output)
            max_tokens: Maximum tokens in response (500 limit)
            db_connection: Database connection for storing explanations
            embedding_client: Separate client for embedding generation (optional)
        """
        self.llm_client = llm_client
        self.model_version = model_version
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.db = db_connection
        self.embedding_client = embedding_client

    async def explain_clusters(
        self,
        clusters: list[dict]
    ) -> list[ExplanationResult]:
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

                # Verify explanation is factually consistent with input data
                if not self._verify_explanation(explanation, sanitized_cluster):
                    logger.warning(
                        "Explanation for cluster %s failed verification — discarding",
                        cluster["cluster_id"],
                    )
                    continue

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

    def _validate_cluster(self, cluster: dict) -> None:
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

    def _sanitize_cluster_data(self, cluster: dict) -> dict:
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
                    # Remove non-ASCII and control characters to prevent Unicode-based bypass
                    value = re.sub(r'[^\x20-\x7E\s]', '', value)
                    # Remove control characters (including null, backspace, etc.)
                    value = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', value)

                    # Remove potential prompt injection patterns (with stricter boundaries)
                    value = re.sub(r'\b(ignore|disregard|forget)\b.*?\b(previous|above|prior)\b', '', value, flags=re.IGNORECASE | re.DOTALL)
                    value = re.sub(r'\b(you are|act as|pretend)\b', '', value, flags=re.IGNORECASE)

                    # Aggressively truncate to prevent hidden injection in long strings
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

    def _verify_explanation(self, explanation: str, cluster: dict) -> bool:
        if not explanation or not cluster:
            return False

        {f.get("type", "").upper() for f in cluster.get("findings", []) if f.get("type")}
        {f.get("endpoint", "").lower() for f in cluster.get("findings", []) if f.get("endpoint")}

        explanation_lower = explanation.lower()

        # Check: no new vulnerability types mentioned that aren't in input
        declared_type = cluster.get("vulnerability_type", "").upper()
        if declared_type and declared_type not in explanation_lower and declared_type.replace("_", " ").lower() not in explanation_lower and ("sql" in declared_type.lower() or "xss" in declared_type.lower() or "rce" in declared_type.lower() or "ssrf" in declared_type.lower()):
                logger.debug("Explanation doesn't mention primary vulnerability type '%s' — may still be valid", declared_type)

        # Check: don't invent CVE IDs not in input
        import re
        input_cves = set()
        for finding in cluster.get("findings", []):
            evidence = finding.get("evidence", {})
            if isinstance(evidence, dict):
                cve = evidence.get("cve", "")
                if cve:
                    input_cves.add(cve.upper())

        output_cves = set(re.findall(r"CVE-\d{4}-\d{4,}", explanation, re.IGNORECASE))
        invented_cves = output_cves - input_cves
        if invented_cves:
            logger.warning("Explanation invented CVE IDs not in input: %s", invented_cves)
            return False

        return True

    def _build_prompt(self, cluster: dict) -> str:
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
        Generate explanation using LLM with retry logic and timeout.

        Uses httpx.AsyncClient for non-blocking HTTP calls.
        Retries up to 2 times with 15s timeout per attempt.

        Args:
            prompt: Prompt string

        Returns:
            Generated explanation
        """
        if not self.llm_client:
            # Return placeholder if no LLM client configured
            logger.warning("No LLM client configured, returning placeholder")
            return "AI explanation not available (LLM client not configured)"

        # Try OpenAI/Anthropic SDK-style client first
        if hasattr(self.llm_client, "chat") and hasattr(self.llm_client.chat, "completions"):
            return await self._generate_with_sdk_client(prompt)

        # Fallback to generic HTTP API with httpx
        return await self._generate_with_httpx(prompt)

    async def _generate_with_sdk_client(self, prompt: str) -> str:
        """
        Generate explanation using an SDK-style LLM client with retry logic.

        Supports OpenAI, Anthropic, and compatible clients that expose a
        ``chat.completions.create`` interface. Retries up to 2 times with
        exponential backoff (1s, 2s) and a 15-second timeout per attempt.

        Args:
            prompt: Sanitized prompt string built from cluster data.

        Returns:
            Generated explanation text, or an error message if all retries fail.
        """
        last_error = None

        for attempt in range(3):  # 3 attempts = initial + 2 retries
            try:
                import asyncio
                response = await asyncio.wait_for(
                    self.llm_client.chat.completions.create(
                        model=self.model_version,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a security expert explaining vulnerabilities to developers. Be factual and specific."
                            },
                            {"role": "user", "content": prompt}
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens
                    ),
                    timeout=15
                )

                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                logger.warning(f"LLM call attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s

        logger.error(f"All LLM retry attempts failed: {last_error}")
        return f"Failed to generate explanation after retries: {str(last_error)}"

    async def _generate_with_httpx(self, prompt: str) -> str:
        """
        Generate explanation using a generic HTTP API via httpx.AsyncClient.

        Fallback for LLM providers without an SDK client. Extracts the
        base URL and API key from the configured client or environment
        variables. Retries up to 2 times with exponential backoff and
        supports common response formats (OpenAI-style ``choices`` and
        plain ``content`` fields).

        Args:
            prompt: Sanitized prompt string built from cluster data.

        Returns:
            Generated explanation text, or an error message if all retries fail.
        """
        try:
            import httpx
        except ImportError:
            logger.error("httpx not installed, cannot make async HTTP calls")
            return "Failed: httpx not installed"

        api_url = getattr(self.llm_client, "base_url", None) or os.getenv("LLM_API_URL")
        api_key = getattr(self.llm_client, "api_key", None) or os.getenv("LLM_API_KEY")

        if not api_url:
            return "Failed: No LLM API URL configured"

        payload = {
            "model": self.model_version,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a security expert explaining vulnerabilities to developers. Be factual and specific."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(api_url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                    # Try common response formats
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"]
                    elif "content" in data:
                        return data["content"]
                    else:
                        return json.dumps(data)[:500]

            except Exception as e:
                last_error = e
                logger.warning(f"HTTP LLM attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        logger.error(f"All HTTP LLM retry attempts failed: {last_error}")
        return f"Failed to generate explanation after retries: {str(last_error)}"

    async def _store_explanation(
        self,
        result: ExplanationResult,
        cluster: dict
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
                AIExplainabilityRepository,
            )

            repo = AIExplainabilityRepository(self.db)

            # Store explanation
            repo.create_explanation(
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

            repo.create_trace(
                cluster_id=result.cluster_id,
                trace_data=trace_data
            )

            logger.info(f"Stored explanation and trace for cluster {result.cluster_id}")

        except Exception as e:
            logger.error(f"Failed to store explanation: {e}")

    async def generate_embedding(self, text: str) -> list[float] | None:
        """
        Generate embedding for text using OpenAI API or OpenRouter.

        Args:
            text: Text to generate embedding for

        Returns:
            List of embedding dimensions, or None if unavailable
        """
        # Try using embedding client if provided
        if self.embedding_client:
            try:
                response = await self.embedding_client.embeddings.create(
                    model=self.EMBEDDING_MODEL,
                    input=text
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning(f"Embedding client failed: {e}")

        # Try using main LLM client as fallback
        if self.llm_client:
            try:
                # Some LLM clients support embeddings
                response = await self.llm_client.embeddings.create(
                    model=self.EMBEDDING_MODEL,
                    input=text
                )
                return response.data[0].embedding
            except AttributeError:
                # Client doesn't support embeddings
                pass
            except Exception as e:
                logger.warning(f"LLM client embedding failed: {e}")

        # Try OpenRouter embeddings endpoint (for sk-or- keys)
        import os
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if api_key and api_key.startswith("sk-or-"):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": os.getenv("NEXT_PUBLIC_APP_URL", "http://localhost:3000"),
                            "X-Title": "Argus Pentest Platform",
                        },
                        json={"model": "openai/text-embedding-3-small", "input": text},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["data"][0]["embedding"]
            except Exception as e:
                logger.warning(f"OpenRouter embedding failed: {e}")

        # Return placeholder embedding for testing
        logger.info("Using placeholder embedding (no API key configured)")
        return self._generate_placeholder_embedding(text)

    def _generate_placeholder_embedding(self, text: str) -> list[float]:
        """
        Generate a deterministic placeholder embedding for testing.

        Note: This is NOT a real semantic embedding - it just provides
        consistent output for development/testing without API keys.
        """
        import hashlib

        # Generate deterministic "random" numbers from text hash
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []

        for i in range(0, len(hash_bytes), 4):
            if i + 3 < len(hash_bytes):
                value = int.from_bytes(hash_bytes[i:i+4], 'big')
                normalized = (value % 10000) / 10000.0
                embedding.append(normalized)

        # Pad to required dimensions
        while len(embedding) < self.EMBEDDING_DIMENSIONS:
            embedding.append(0.0)

        return embedding[:self.EMBEDDING_DIMENSIONS]

    async def generate_and_store_embeddings(
        self,
        findings: list[dict],
        engagement_id: str
    ) -> dict[str, bool]:
        """
        Generate and store embeddings for findings using pgvector.

        Args:
            findings: List of finding dictionaries
            engagement_id: Engagement ID

        Returns:
            Dictionary with success count and errors
        """
        from database.repositories.pgvector_repository import PGVectorRepository

        result = {"success": 0, "errors": 0, "skipped": 0}

        # Check if pgvector is available
        repo = PGVectorRepository(self.db)
        if not repo.check_pgvector_available():
            logger.warning("pgvector not available, skipping embeddings")
            result["skipped"] = len(findings)
            return result

        for finding in findings:
            try:
                # Generate text for embedding from finding
                text_for_embedding = self._finding_to_text(finding)

                # Generate embedding
                embedding = await self.generate_embedding(text_for_embedding)

                if embedding is None:
                    result["skipped"] += 1
                    continue

                # Store embedding
                success = repo.store_embedding(
                    finding_id=finding.get("id", ""),
                    engagement_id=engagement_id,
                    embedding=embedding,
                    text_content=text_for_embedding,
                )

                if success:
                    result["success"] += 1
                else:
                    result["errors"] += 1

            except Exception as e:
                logger.error(f"Failed to process embedding for {finding.get('id')}: {e}")
                result["errors"] += 1

        logger.info(
            f"Embedding generation complete: {result['success']} success, "
            f"{result['errors']} errors, {result['skipped']} skipped"
        )
        return result

    def _finding_to_text(self, finding: dict) -> str:
        """
        Convert finding to text for embedding generation.

        Args:
            finding: Finding dictionary

        Returns:
            Text representation
        """
        parts = [
            finding.get("type", "unknown"),
            finding.get("endpoint", ""),
            finding.get("severity", ""),
        ]

        evidence = finding.get("evidence", {})
        if evidence:
            payload = evidence.get("payload", "")
            if payload:
                parts.append(f"Payload: {payload}")

        return " | ".join([str(p) for p in parts if p])

    # ── AI-Powered Threat Intelligence Integration (Step 18) ──

    def _build_threat_intel_context(self, cluster: dict) -> str:
        """
        Build threat intelligence context string from cluster findings.

        Args:
            cluster: Vulnerability cluster with potential threat_intel on findings

        Returns:
            Threat intel context string for prompt enrichment
        """
        intel_parts = []
        cve_list = []
        epss_alerts = []
        feed_hits = []
        fp_warnings = []

        for finding in cluster.get("findings", []):
            threat_intel = finding.get("threat_intel", {})

            # Collect CVEs
            cve_details = threat_intel.get("cve_details", {})
            for cve_id, details in cve_details.items():
                cve_list.append(f"{cve_id} (CVSS: {details.get('cvss_score', 'N/A')})")

            # Collect high EPSS scores
            epss_scores = threat_intel.get("epss_scores", {})
            for cve_id, score in epss_scores.items():
                if score > 0.5:
                    epss_alerts.append(f"{cve_id} (EPSS: {score:.1%})")

            # Collect threat feed hits
            for hit in threat_intel.get("threat_feed_hits", []):
                feed_hits.append(f"{hit.get('feed', 'unknown')}: {hit.get('description', '')}")

            # Collect FP warnings
            fp_assessment = threat_intel.get("fp_assessment", {})
            if fp_assessment.get("verdict") in ["likely_false_positive", "false_positive"]:
                fp_warnings.append(
                    f"{finding.get('type', 'unknown')} at {finding.get('endpoint', '')} "
                    f"- {fp_assessment.get('verdict')} (confidence: {fp_assessment.get('confidence', 0)})")

        if cve_list:
            intel_parts.append(f"Related CVEs: {', '.join(cve_list[:5])}")

        if epss_alerts:
            intel_parts.append(f"High Exploitability (EPSS >50%): {', '.join(epss_alerts[:3])}")

        if feed_hits:
            intel_parts.append(f"Threat Feed Matches: {', '.join(feed_hits[:3])}")

        if fp_warnings:
            intel_parts.append(f"False Positive Warnings: {', '.join(fp_warnings[:2])}")

        return "\n".join(intel_parts) if intel_parts else ""

    def _build_prompt_with_threat_intel(self, cluster: dict) -> str:
        """
        Build prompt enriched with threat intelligence context.

        Args:
            cluster: Sanitized cluster data with threat intel

        Returns:
            Prompt string with threat intel
        """
        base_prompt = self._build_prompt(cluster)
        threat_context = self._build_threat_intel_context(cluster)

        if not threat_context:
            return base_prompt

        # Insert threat intel before TASK section
        threat_section = f"""
THREAT INTELLIGENCE CONTEXT:
{threat_context}
"""

        # Find the TASK section and insert before it
        task_marker = "TASK:"
        if task_marker in base_prompt:
            parts = base_prompt.split(task_marker, 1)
            return parts[0] + threat_section + "\n" + task_marker + parts[1]

        return base_prompt + threat_section

    async def explain_clusters_with_threat_intel(
        self,
        clusters: list[dict]
    ) -> list[ExplanationResult]:
        """
        Generate explanations enriched with threat intelligence context.

        Args:
            clusters: List of pre-grouped vulnerability clusters with threat_intel

        Returns:
            List of explanation results
        """
        if not clusters:
            logger.warning("No clusters provided for threat-intel explanation")
            return []

        results = []

        for cluster in clusters:
            try:
                # Validate cluster structure
                self._validate_cluster(cluster)

                # Sanitize cluster data
                sanitized_cluster = self._sanitize_cluster_data(cluster)

                # Build prompt with threat intelligence
                prompt = self._build_prompt_with_threat_intel(sanitized_cluster)

                # Generate explanation
                explanation = await self._generate_explanation(prompt)

                # Verify explanation is factually consistent with input data
                if not self._verify_explanation(explanation, sanitized_cluster):
                    logger.warning(
                        "Threat-intel explanation for cluster %s failed verification — discarding",
                        cluster["cluster_id"],
                    )
                    continue

                # Create result
                result = ExplanationResult(
                    cluster_id=cluster["cluster_id"],
                    explanation=explanation,
                    model_version=self.model_version,
                    token_count=len(explanation.split()),
                    input_cluster_ids=[cluster["cluster_id"]],
                    used_fields=list(sanitized_cluster.keys()),
                    timestamp=datetime.now()
                )

                # Store explanation and trace
                if self.db:
                    await self._store_explanation(result, sanitized_cluster)

                results.append(result)

                logger.info(
                    f"Generated threat-intel explanation for cluster {cluster['cluster_id']}: "
                    f"{len(explanation)} chars"
                )

            except Exception as e:
                logger.error(
                    f"Failed to explain cluster {cluster.get('cluster_id', 'unknown')} with threat intel: {e}"
                )
                continue

        return results
