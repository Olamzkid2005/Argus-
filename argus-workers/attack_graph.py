"""
Attack Graph Engine - Computes probabilistic risk scores with confidence decay

Includes Bug-Reaper vulnerability chaining templates for detecting
high-value attack chains that escalate individual findings to critical severity.
"""

import math
from typing import Any

from models.finding import VulnerabilityFinding
from tool_core._compat import StrEnum


class RelationshipType(StrEnum):
    """Semantic relationship between graph nodes."""

    CAUSES = "causes"
    AMPLIFIES = "amplifies"
    ENABLES = "enables"
    DEPENDS_ON = "depends_on"
    MITIGATES = "mitigates"
    INDEPENDENT = "independent"


# ═══════════════════════════════════════════════════════════════════════════════
# Bug-Reaper Chain Templates
# ═══════════════════════════════════════════════════════════════════════════════
# High-value chain templates that convert P3/P4 findings ($200-500) into
# P1/P2 findings ($5,000-50,000). Source: agent/bugbounty_knowledge/chaining.md

CHAIN_RULES: list[dict[str, Any]] = [
    {
        "id": "chain_1",
        "name": "Open Redirect → OAuth Authorization Code Theft → ATO",
        "severity": "CRITICAL",
        "prerequisites": ["open_redirect"],
        "chain": ["open_redirect", "auth"],
        "correlation_factor": 1.5,
        "description": "OAuth validates redirect_uri as prefix, enabling code theft via redirect parameter",
    },
    {
        "id": "chain_2",
        "name": "XSS + CSRF → Account Takeover",
        "severity": "CRITICAL",
        "prerequisites": ["xss"],
        "chain": ["xss", "csrf"],
        "correlation_factor": 1.4,
        "description": "XSS reads CSRF token from DOM, enables authenticated actions as victim",
    },
    {
        "id": "chain_3",
        "name": "SSRF → Cloud Metadata → Full AWS Compromise",
        "severity": "CRITICAL",
        "prerequisites": ["ssrf"],
        "chain": ["ssrf", "cloud_metadata"],
        "correlation_factor": 1.5,
        "description": "SSRF to IMDS (169.254.169.254) extracts AWS credentials for full account takeover",
    },
    {
        "id": "chain_4",
        "name": "LFI + File Upload → Remote Code Execution",
        "severity": "CRITICAL",
        "prerequisites": ["lfi"],
        "chain": ["lfi", "rce"],
        "correlation_factor": 1.5,
        "description": "Upload PHP file, LFI includes it to achieve RCE",
    },
    {
        "id": "chain_5",
        "name": "Subdomain Takeover + CORS → Credential Theft",
        "severity": "CRITICAL",
        "prerequisites": ["subdomain_takeover"],
        "chain": ["subdomain_takeover", "cors"],
        "correlation_factor": 1.4,
        "description": "Claim subdomain, use CORS (*.target.com + credentials: true) to read API responses",
    },
    {
        "id": "chain_6",
        "name": "XSS → Session Token Theft → ATO",
        "severity": "HIGH",
        "prerequisites": ["xss"],
        "chain": ["xss", "session_theft"],
        "correlation_factor": 1.4,
        "description": "XSS steals non-HttpOnly cookie, attacker uses token to authenticate as victim",
    },
    {
        "id": "chain_7",
        "name": "IDOR + Mass Assignment → Privilege Escalation",
        "severity": "HIGH",
        "prerequisites": ["idor"],
        "chain": ["idor", "privilege_escalation"],
        "correlation_factor": 1.3,
        "description": "IDOR on user update endpoint + mass assignment (server accepts role field) = admin access",
    },
    {
        "id": "chain_8",
        "name": "Open Redirect + Phishing",
        "severity": "MEDIUM",
        "prerequisites": ["open_redirect"],
        "chain": ["open_redirect", "phishing"],
        "correlation_factor": 1.1,
        "description": "Open redirect to lookalike domain for credential harvesting (requires social engineering)",
    },
]

# Mapping of Argus finding types to chain prerequisite types
TYPE_TO_CHAIN_PREREQ = {
    "XSS": "xss",
    "REFLECTED_XSS": "xss",
    "STORED_XSS": "xss",
    "DOM_XSS": "xss",
    "BLIND_XSS": "xss",
    "SSRF": "ssrf",
    "IDOR": "idor",
    "BOLA": "idor",
    "LFI": "lfi",
    "PATH_TRAVERSAL": "lfi",
    "DIRECTORY_TRAVERSAL": "lfi",
    "OPEN_REDIRECT": "open_redirect",
    "CORS": "cors",
    "CORS_MISCONFIGURATION": "cors",
    "SUBDOMAIN_TAKEOVER": "subdomain_takeover",
    "CSRF": "csrf",
    "RCE": "rce",
    "COMMAND_INJECTION": "rce",
    "AUTH_BYPASS": "auth",
    "BROKEN_AUTH": "auth",
    "BROKEN_AUTHENTICATION": "auth",
}


class Node:
    """Graph node representing vulnerability or endpoint"""

    def __init__(
        self,
        node_id: str,
        node_type: str,
        data: dict,
        cvss: float | None = None,
        confidence: float | None = None,
        prerequisites: list[str] | None = None,
        downstream_impacts: list[str] | None = None,
    ):
        self.id = node_id
        self.type = node_type  # "vulnerability" or "endpoint"
        self.data = data
        self.cvss = cvss
        self.confidence = confidence
        self.prerequisites = prerequisites or []
        self.downstream_impacts = downstream_impacts or []


class Edge:
    """Graph edge connecting nodes"""

    def __init__(
        self,
        from_node: str,
        to_node: str,
        edge_type: str,
        correlation_factor: float,
        relationship_type: RelationshipType = RelationshipType.INDEPENDENT,
    ):
        self.from_node = from_node
        self.to_node = to_node
        self.type = edge_type
        self.correlation_factor = correlation_factor
        self.relationship_type = relationship_type


class Path:
    """Attack path through the graph"""

    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes = nodes
        self.edges = edges


class AttackGraph:
    """
    Attack Graph Engine for computing probabilistic risk scores
    """

    # Edge type correlation factors
    CORRELATION_FACTORS = {
        "causes": 1.5,
        "amplifies": 1.3,
        "enables": 1.2,
        "depends_on": 0.8,
        "independent": 1.0,
    }

    # Relationship-aware correlation factors (supersedes CORRELATION_FACTORS)
    RELATIONSHIP_CORRELATION = {
        RelationshipType.CAUSES: 1.5,
        RelationshipType.AMPLIFIES: 1.3,
        RelationshipType.ENABLES: 1.4,
        RelationshipType.DEPENDS_ON: 0.8,
        RelationshipType.MITIGATES: 0.5,
        RelationshipType.INDEPENDENT: 1.0,
    }

    # Map finding type to exploitation prerequisites
    PREREQ_MAP = {
        "SSRF": ["outbound_fetch_capability"],
        "XSS": ["user_interaction", "no_csp"],
        "REFLECTED_XSS": ["user_interaction", "no_csp"],
        "STORED_XSS": ["no_csp"],
        "DOM_XSS": ["user_interaction"],
        "BLIND_XSS": [],
        "SQL_INJECTION": ["parametrized_query_bypassed"],
        "IDOR": ["authenticated_session", "sequential_id"],
        "BOLA": ["authenticated_session"],
        "LFI": ["file_read_enabled"],
        "PATH_TRAVERSAL": ["file_read_enabled"],
        "DIRECTORY_TRAVERSAL": ["file_read_enabled"],
        "RCE": ["code_exec_sink_reachable"],
        "COMMAND_INJECTION": ["code_exec_sink_reachable"],
        "OPEN_REDIRECT": ["external_redirect_allowed"],
        "AUTH_BYPASS": ["public_endpoint"],
        "BROKEN_AUTH": ["public_endpoint"],
        "BROKEN_AUTHENTICATION": ["public_endpoint"],
        "CSRF": ["authenticated_session"],
        "CORS": ["authenticated_session"],
        "CORS_MISCONFIGURATION": ["authenticated_session"],
        "SUBDOMAIN_TAKEOVER": ["dangling_dns"],
    }

    # Map finding type to downstream impacts
    IMPACT_MAP = {
        "SSRF": ["credential_access", "internal_service_discovery"],
        "XSS": ["session_theft", "credential_capture", "malicious_action"],
        "REFLECTED_XSS": ["session_theft", "credential_capture"],
        "STORED_XSS": ["malicious_action", "credential_capture"],
        "DOM_XSS": ["session_theft"],
        "BLIND_XSS": ["credential_capture"],
        "SQL_INJECTION": ["data_exfiltration", "auth_bypass"],
        "IDOR": ["unauthorized_data_access", "privilege_escalation"],
        "BOLA": ["unauthorized_data_access"],
        "LFI": ["file_disclosure", "rce_chainable"],
        "PATH_TRAVERSAL": ["file_disclosure"],
        "DIRECTORY_TRAVERSAL": ["file_disclosure"],
        "RCE": ["full_system_compromise"],
        "COMMAND_INJECTION": ["full_system_compromise"],
        "OPEN_REDIRECT": ["phishing_chainable", "oauth_token_theft"],
        "AUTH_BYPASS": ["privilege_escalation", "data_exfiltration"],
        "BROKEN_AUTH": ["privilege_escalation"],
        "BROKEN_AUTHENTICATION": ["privilege_escalation", "data_exfiltration"],
        "CSRF": ["malicious_action"],
        "CORS": ["data_exfiltration"],
        "CORS_MISCONFIGURATION": ["data_exfiltration"],
        "SUBDOMAIN_TAKEOVER": ["credential_capture", "malicious_action"],
    }

    # Exposure factors
    EXPOSURE_FACTORS = {
        "public": 1.0,
        "authenticated": 0.7,
        "internal": 0.4,
    }

    # Severity value map for comparison (higher = more severe)
    SEVERITY_VALUES = {
        "CRITICAL": 5,
        "HIGH": 4,
        "MEDIUM": 3,
        "LOW": 2,
        "INFO": 1,
    }

    def __init__(self, engagement_id: str):
        """
        Initialize Attack Graph

        Args:
            engagement_id: Engagement ID
        """
        self.engagement_id = engagement_id
        self.nodes: dict[str, Node] = {}  # node_id -> Node
        self.edges: list[Edge] = []  # List of edges

    def _get_severity_value(self, severity) -> int:
        """Get numeric severity value for comparison"""
        sev = severity.value if hasattr(severity, "value") else severity
        return self.SEVERITY_VALUES.get(sev, 3)

    def add_finding(self, finding: VulnerabilityFinding) -> None:
        """
        Add finding as vulnerability node

        Creates or updates vulnerability node and endpoint node, connects them with edge.
        If same finding type+endpoint exists with higher severity, updates the node.

        Args:
            finding: VulnerabilityFinding instance
        """
        # Get severity value for the new finding
        finding_severity = (
            finding.severity.value
            if hasattr(finding.severity, "value")
            else finding.severity
        )

        # Create vulnerability node ID (without severity to track uniqueness)
        vuln_node_id = f"vuln_{finding.type}_{finding.endpoint}"

        # Check if finding already exists
        if vuln_node_id in self.nodes:
            existing_node = self.nodes[vuln_node_id]
            existing_severity = existing_node.data.get("severity", "MEDIUM")
            existing_severity_value = self._get_severity_value(existing_severity)
            new_severity_value = self._get_severity_value(finding_severity)

            # Only update if new finding has higher severity
            if new_severity_value > existing_severity_value:
                existing_node.data["severity"] = finding_severity
                existing_node.data["source_tool"] = finding.source_tool
                existing_node.cvss = (
                    finding.cvss_score
                    if finding.cvss_score is not None
                    else self._estimate_cvss(finding_severity)
                )
                # Update confidence to max of existing and new
                if finding.confidence and finding.confidence > (
                    existing_node.confidence or 0
                ):
                    existing_node.confidence = finding.confidence
            return

        # Create new vulnerability node
        vuln_node = Node(
            node_id=vuln_node_id,
            node_type="vulnerability",
            data={
                "type": finding.type,
                "severity": finding_severity,
                "endpoint": finding.endpoint,
                "source_tool": finding.source_tool,
            },
            cvss=finding.cvss_score
            if finding.cvss_score is not None
            else self._estimate_cvss(finding_severity),
            confidence=finding.confidence,
        )
        self.nodes[vuln_node_id] = vuln_node

        # Create endpoint node
        endpoint_node_id = f"endpoint_{finding.endpoint}"
        if endpoint_node_id not in self.nodes:
            endpoint_node = Node(
                node_id=endpoint_node_id,
                node_type="endpoint",
                data={"url": finding.endpoint},
            )
            self.nodes[endpoint_node_id] = endpoint_node

        # Set prerequisites and downstream_impacts from maps
        vuln_node.prerequisites = self._infer_prerequisites(finding.type)
        vuln_node.downstream_impacts = self._infer_downstream_impacts(finding.type)

        # Create edge connecting vulnerability to endpoint
        edge = Edge(
            from_node=vuln_node_id,
            to_node=endpoint_node_id,
            edge_type="independent",  # Default edge type
            correlation_factor=self.CORRELATION_FACTORS["independent"],
            relationship_type=self._infer_relationship(finding.type),
        )
        self.edges.append(edge)

    def _infer_prerequisites(self, finding_type: str) -> list[str]:
        """Map finding type to exploitation prerequisites."""
        return list(self.PREREQ_MAP.get(finding_type.upper(), []))

    def _infer_downstream_impacts(self, finding_type: str) -> list[str]:
        """Map finding type to downstream impacts."""
        return list(self.IMPACT_MAP.get(finding_type.upper(), []))

    def _infer_relationship(self, finding_type: str) -> RelationshipType:
        """
        Infer the default relationship type for a finding type.

        Vulnerabilities that directly enable further exploitation get ENABLES.
        Vulnerabilities that increase impact severity get AMPLIFIES.
        All others default to INDEPENDENT.
        """
        enables_types = {
            "SSRF",
            "RCE",
            "COMMAND_INJECTION",
            "IDOR",
            "BOLA",
            "LFI",
            "PATH_TRAVERSAL",
            "DIRECTORY_TRAVERSAL",
            "AUTH_BYPASS",
            "BROKEN_AUTH",
            "BROKEN_AUTHENTICATION",
        }
        amplifies_types = {
            "XSS",
            "REFLECTED_XSS",
            "STORED_XSS",
            "DOM_XSS",
            "BLIND_XSS",
            "CSRF",
            "CORS",
            "CORS_MISCONFIGURATION",
            "SUBDOMAIN_TAKEOVER",
            "OPEN_REDIRECT",
        }

        ft = finding_type.upper()
        if ft in enables_types:
            return RelationshipType.ENABLES
        elif ft in amplifies_types:
            return RelationshipType.AMPLIFIES
        return RelationshipType.INDEPENDENT

    def _get_chain_prereq(self, finding_type: str) -> str | None:
        """Map finding type to chain prerequisite type."""
        return TYPE_TO_CHAIN_PREREQ.get(finding_type.upper())

    def find_chains(self) -> list[dict[str, Any]]:
        """
        Detect vulnerability chains in the graph.

        When two findings share an engagement and their types match a chain template,
        they form a chain that escalates severity.

        Returns:
            List of detected chain dictionaries with chain_id, severity, nodes, and multiplier
        """
        chains = []

        # Get all vulnerability nodes
        vuln_nodes = [
            (node_id, node)
            for node_id, node in self.nodes.items()
            if node.type == "vulnerability"
        ]

        for chain_rule in CHAIN_RULES:
            prereq_type = chain_rule["prerequisites"][0]

            # Find nodes matching prerequisite type
            prereq_nodes = [
                (node_id, node)
                for node_id, node in vuln_nodes
                if self._get_chain_prereq(node.data.get("type", "")) == prereq_type
            ]

            for prereq_node_id, prereq_node in prereq_nodes:
                # Look for second-stage vulnerabilities in the chain
                for chain_type in chain_rule["chain"][1:]:
                    # Find matching second node (on same or different endpoint)
                    for node_id, node in vuln_nodes:
                        if node_id == prereq_node_id:
                            continue
                        if (
                            self._get_chain_prereq(node.data.get("type", ""))
                            == chain_type
                        ):
                            # Chain detected
                            chains.append(
                                {
                                    "chain_id": chain_rule["id"],
                                    "name": chain_rule["name"],
                                    "severity": chain_rule["severity"],
                                    "correlation_factor": chain_rule[
                                        "correlation_factor"
                                    ],
                                    "prereq_node": prereq_node,
                                    "chain_node": node,
                                    "description": chain_rule["description"],
                                }
                            )

        return chains

    def get_all_paths_with_chains(self) -> list[Path]:
        """
        Get all attack paths including chain-enhanced paths.

        When a chain is detected, the path includes both vulnerabilities
        with the chain's correlation factor applied.

        Returns:
            List of attack paths including chain-enhanced paths
        """
        paths = []

        # Get basic paths
        for edge in self.edges:
            from_node = self.nodes.get(edge.from_node)
            to_node = self.nodes.get(edge.to_node)

            if from_node and to_node:
                path = Path(nodes=[from_node, to_node], edges=[edge])
                paths.append(path)

        # Add chain-enhanced paths
        chains = self.find_chains()
        for chain in chains:
            # Create a chain path with both vulnerabilities
            chain_path = Path(
                nodes=[chain["prereq_node"], chain["chain_node"]], edges=[]
            )
            paths.append(chain_path)

        return paths

    def get_highest_risk_paths(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get highest risk paths including chain bonuses.

        Chain paths receive elevated risk scores based on chain correlation factor.

        Args:
            limit: Maximum number of paths to return

        Returns:
            List of path dictionaries with risk scores
        """
        paths = self.get_all_paths_with_chains()

        # Calculate risk for each path
        path_risks: list[dict[str, Any]] = []
        chains = self.find_chains()
        from collections import defaultdict

        chain_map: dict[str, list[dict]] = defaultdict(list)
        for c in chains:
            chain_map[c["prereq_node"].id].append(c)

        for path in paths:
            risk = self.compute_risk(path)

            # Apply chain bonus if this is a chain path (all matching chains)
            if len(path.nodes) >= 2 and path.nodes[0].id in chain_map:
                chain = chain_map[path.nodes[0].id][0]
                risk *= chain["correlation_factor"]

            path_risks.append(
                {
                    "path": path,
                    "risk_score": risk,
                    "nodes": [
                        {
                            "id": node.id,
                            "type": node.type,
                            "data": node.data,
                        }
                        for node in path.nodes
                    ],
                }
            )

        # Sort by risk score descending
        path_risks.sort(key=lambda x: float(x["risk_score"]), reverse=True)

        return path_risks[:limit]

    def compute_risk(self, path: Path, exposure: str = "public") -> float:
        """
        Compute risk using:
        risk = base_risk × confidence_weight × chain_multiplier × exposure_factor

        Args:
            path: Attack path
            exposure: Exposure level (public, authenticated, internal)

        Returns:
            Risk score (0.0-10.0)
        """
        # Calculate base risk (average CVSS)
        base_risk = self._calculate_base_risk(path)

        # Calculate confidence weight (geometric mean with decay)
        confidence_weight = self.compute_confidence_decay(path)

        # Calculate chain multiplier
        chain_multiplier = self._calculate_chain_multiplier(path)

        # Get exposure factor
        exposure_factor = self.EXPOSURE_FACTORS.get(exposure, 1.0)

        # Compute risk
        risk = base_risk * confidence_weight * chain_multiplier * exposure_factor

        # Normalize to max 10.0
        return min(10.0, risk)

    def _calculate_base_risk(self, path: Path) -> float:
        """
        Calculate base risk as average CVSS score

        Args:
            path: Attack path

        Returns:
            Base risk score
        """
        cvss_scores = [node.cvss for node in path.nodes if node.cvss is not None]

        if not cvss_scores:
            return 5.0  # Default medium risk

        return sum(cvss_scores) / len(cvss_scores)

    def compute_confidence_decay(self, path: Path) -> float:
        """
        Confidence decays across chain length (geometric mean)

        Penalizes low confidence in chains.

        Args:
            path: Attack path

        Returns:
            Confidence weight (0.0-1.0)
        """
        confidences = [
            node.confidence for node in path.nodes if node.confidence is not None
        ]

        if not confidences:
            return 0.5  # Default medium confidence

        # Geometric mean
        product = 1.0
        for conf in confidences:
            product *= conf

        return math.pow(product, 1.0 / len(confidences))

    def _calculate_chain_multiplier(self, path: Path) -> float:
        """
        Calculate chain multiplier: 1 + (0.2 × (path_length - 1))

        Args:
            path: Attack path

        Returns:
            Chain multiplier
        """
        path_length = len(path.nodes)
        return 1.0 + (0.2 * (path_length - 1))

    @staticmethod
    def _estimate_cvss(severity: str) -> float:
        """
        Estimate CVSS score from severity

        Args:
            severity: Severity level

        Returns:
            Estimated CVSS score
        """
        severity_to_cvss = {
            "CRITICAL": 9.5,
            "HIGH": 7.5,
            "MEDIUM": 5.0,
            "LOW": 3.0,
            "INFO": 0.0,
        }

        return severity_to_cvss.get(severity, 5.0)

    def compute_exploitability(
        self, path: Path, satisfied_prerequisites: set[str]
    ) -> float:
        """
        Compute how exploitable a path is given satisfied prerequisites.

        Returns the fraction of path node prerequisites that are satisfied.
        A path where all prerequisites are met returns 1.0 (fully exploitable).
        A path with no prerequisites returns 1.0 (always exploitable).
        A path where no prerequisites are met returns 0.0.

        Args:
            path: Attack path to evaluate
            satisfied_prerequisites: Set of prerequisite conditions that are met

        Returns:
            Exploitability score (0.0-1.0)
        """
        all_prereqs = set()
        for node in path.nodes:
            all_prereqs.update(node.prerequisites)

        if not all_prereqs:
            return 1.0

        satisfied = all_prereqs & satisfied_prerequisites
        return len(satisfied) / len(all_prereqs)

    def get_downstream_paths(self, node_id: str) -> list[Path]:
        """
        Return all paths where this node is a starting point.

        Enables queries like "Given SSRF at endpoint X, what attacks does it enable?"
        Returns paths starting from node_id through all outgoing edges.

        Args:
            node_id: The node ID to find downstream paths from

        Returns:
            List of paths originating from the given node
        """
        if node_id not in self.nodes:
            return []

        start_node = self.nodes[node_id]
        downstream = []

        # Find all edges originating from this node
        for edge in self.edges:
            if edge.from_node == node_id:
                to_node = self.nodes.get(edge.to_node)
                if to_node:
                    downstream.append(
                        Path(
                            nodes=[start_node, to_node],
                            edges=[edge],
                        )
                    )

        # Also check chain rules where this node is the prerequisite
        chains = self.find_chains()
        for chain in chains:
            prereq_node: Node = chain["prereq_node"]
            chain_node: Node = chain["chain_node"]
            if prereq_node.id == node_id:
                downstream.append(
                    Path(
                        nodes=[prereq_node, chain_node],
                        edges=[],
                    )
                )

        return downstream

    def to_snapshot_dict(self) -> dict[str, Any]:
        """
        Serialize the attack graph to a dictionary for snapshot storage.

        Produces the dict used by SnapshotManager for decision_snapshots,
        including all nodes, edges, relationships, prerequisites, and impacts.

        Returns:
            Dict with 'paths' key containing serialized path data
        """
        paths = self.get_all_paths_with_chains()

        serialized_paths = []
        for path in paths:
            risk = self.compute_risk(path)
            serialized_paths.append(
                {
                    "risk_score": round(risk, 2),
                    "nodes": [
                        {
                            "id": node.id,
                            "type": node.type,
                            "data": node.data,
                            "cvss": node.cvss,
                            "confidence": node.confidence,
                            "prerequisites": list(node.prerequisites),
                            "downstream_impacts": list(node.downstream_impacts),
                        }
                        for node in path.nodes
                    ],
                    "edges": [
                        {
                            "from_node": edge.from_node,
                            "to_node": edge.to_node,
                            "type": edge.type,
                            "correlation_factor": edge.correlation_factor,
                            "relationship_type": str(edge.relationship_type),
                        }
                        for edge in path.edges
                    ],
                }
            )

        return {"paths": serialized_paths}

    def get_all_paths(self) -> list[Path]:
        """
        Get all attack paths in the graph

        Returns:
            List of attack paths
        """
        # Simple implementation: each vulnerability-endpoint pair is a path
        paths = []

        for edge in self.edges:
            from_node = self.nodes.get(edge.from_node)
            to_node = self.nodes.get(edge.to_node)

            if from_node and to_node:
                path = Path(nodes=[from_node, to_node], edges=[edge])
                paths.append(path)

        return paths

    def generate_plan_from_graph(self) -> list[dict[str, Any]]:
        """
        Generate an ordered list of exploitation phases from detected attack chains.

        Each detected chain is converted into a phase plan that the TypeScript
        planner can insert into the workflow. Chains with higher risk scores
        and CRITICAL severity are prioritized.

        Returns:
            List of phase plan dicts, each with:
            - chain_id: str — matches CHAIN_RULES[].id
            - name: str — human-readable chain name
            - severity: str — overall chain severity
            - risk_score: float — computed risk score
            - prerequisite_finding_types: list[str] — finding types that triggered this chain
            - suggested_capabilities: list[str] — what capabilities to run next
            - description: str — chain description
        """
        chains = self.find_chains()
        if not chains:
            return []

        # Map chain IDs to suggested capabilities for exploitation
        CHAIN_TO_CAPABILITIES: dict[str, list[str]] = {
            "chain_1": ["open_redirect", "auth"],
            "chain_2": ["xss", "csrf"],
            "chain_3": ["cloud_metadata_probe", "post_exploitation"],
            "chain_4": ["lfi", "command_injection"],
            "chain_5": ["subdomain_takeover", "cors"],
            "chain_6": ["xss", "session_hijack_attempt"],
            "chain_7": ["idor", "privilege_escalation"],
            "chain_8": ["open_redirect", "phishing_chain"],
        }

        # Collect unique chain results
        seen = set()
        plans: list[dict[str, Any]] = []
        for chain in chains:
            chain_id = chain.get("chain_id", "")
            if chain_id in seen:
                continue
            seen.add(chain_id)

            prereq_node = chain.get("prereq_node")
            chain_node = chain.get("chain_node")
            prereq_type = str(prereq_node.data.get("type", "")) if prereq_node else ""
            chain_type = str(chain_node.data.get("type", "")) if chain_node else ""

            # Compute risk score from the chain path
            path = Path(nodes=[prereq_node, chain_node], edges=[]) if prereq_node and chain_node else None
            risk_score = self.compute_risk(path) if path else 0.0

            plans.append({
                "chain_id": chain_id,
                "name": chain.get("name", "Unknown chain"),
                "severity": chain.get("severity", "MEDIUM"),
                "risk_score": round(risk_score, 2),
                "prerequisite_finding_types": [prereq_type, chain_type],
                "suggested_capabilities": CHAIN_TO_CAPABILITIES.get(chain_id, []),
                "description": chain.get("description", ""),
            })

        # Sort by severity (CRITICAL first) then risk score descending
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        plans.sort(key=lambda p: (severity_order.get(p["severity"], 5), -p["risk_score"]))

        return plans
