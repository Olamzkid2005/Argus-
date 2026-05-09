"""
Attack Graph Engine - Computes probabilistic risk scores with confidence decay

Includes Bug-Reaper vulnerability chaining templates for detecting
high-value attack chains that escalate individual findings to critical severity.
"""
import math

from models.finding import VulnerabilityFinding

# ═══════════════════════════════════════════════════════════════════════════════
# Bug-Reaper Chain Templates
# ═══════════════════════════════════════════════════════════════════════════════
# High-value chain templates that convert P3/P4 findings ($200-500) into
# P1/P2 findings ($5,000-50,000). Source: agent/bugbounty_knowledge/chaining.md

CHAIN_RULES = [
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
        confidence: float | None = None
    ):
        self.id = node_id
        self.type = node_type  # "vulnerability" or "endpoint"
        self.data = data
        self.cvss = cvss
        self.confidence = confidence


class Edge:
    """Graph edge connecting nodes"""

    def __init__(
        self,
        from_node: str,
        to_node: str,
        edge_type: str,
        correlation_factor: float
    ):
        self.from_node = from_node
        self.to_node = to_node
        self.type = edge_type
        self.correlation_factor = correlation_factor


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
        self.nodes = {}  # node_id -> Node
        self.edges = []  # List of edges

    def _get_severity_value(self, severity) -> int:
        """Get numeric severity value for comparison"""
        sev = severity.value if hasattr(severity, 'value') else severity
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
        finding_severity = finding.severity.value if hasattr(finding.severity, 'value') else finding.severity

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
                existing_node.cvss = finding.cvss_score or self._estimate_cvss(finding_severity)
                # Update confidence to max of existing and new
                if finding.confidence and finding.confidence > (existing_node.confidence or 0):
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
            cvss=finding.cvss_score or self._estimate_cvss(finding_severity),
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

        # Create edge connecting vulnerability to endpoint
        edge = Edge(
            from_node=vuln_node_id,
            to_node=endpoint_node_id,
            edge_type="independent",  # Default edge type
            correlation_factor=self.CORRELATION_FACTORS["independent"],
        )
        self.edges.append(edge)

    def _get_chain_prereq(self, finding_type: str) -> str | None:
        """Map finding type to chain prerequisite type."""
        return TYPE_TO_CHAIN_PREREQ.get(finding_type.upper())

    def find_chains(self) -> list[dict]:
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
            (node_id, node) for node_id, node in self.nodes.items()
            if node.type == "vulnerability"
        ]

        for chain_rule in CHAIN_RULES:
            prereq_type = chain_rule["prerequisites"][0]

            # Find nodes matching prerequisite type
            prereq_nodes = [
                (node_id, node) for node_id, node in vuln_nodes
                if self._get_chain_prereq(node.data.get("type", "")) == prereq_type
            ]

            for prereq_node_id, prereq_node in prereq_nodes:
                # Look for second-stage vulnerabilities in the chain
                for chain_type in chain_rule["chain"][1:]:
                    # Find matching second node (on same or different endpoint)
                    for node_id, node in vuln_nodes:
                        if node_id == prereq_node_id:
                            continue
                        if self._get_chain_prereq(node.data.get("type", "")) == chain_type:
                            # Chain detected
                            chains.append({
                                "chain_id": chain_rule["id"],
                                "name": chain_rule["name"],
                                "severity": chain_rule["severity"],
                                "correlation_factor": chain_rule["correlation_factor"],
                                "prereq_node": prereq_node,
                                "chain_node": node,
                                "description": chain_rule["description"],
                            })

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
                path = Path(
                    nodes=[from_node, to_node],
                    edges=[edge]
                )
                paths.append(path)

        # Add chain-enhanced paths
        chains = self.find_chains()
        for chain in chains:
            # Create a chain path with both vulnerabilities
            chain_path = Path(
                nodes=[chain["prereq_node"], chain["chain_node"]],
                edges=[]
            )
            paths.append(chain_path)

        return paths

    def get_highest_risk_paths(self, limit: int = 10) -> list[dict]:
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
        path_risks = []
        chains = self.find_chains()
        chain_map = {c["prereq_node"].id: c for c in chains}

        for path in paths:
            risk = self.compute_risk(path)

            # Apply chain bonus if this is a chain path
            if len(path.nodes) >= 2 and path.nodes[0].id in chain_map:
                chain = chain_map[path.nodes[0].id]
                risk *= chain["correlation_factor"]

            path_risks.append({
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
            })

        # Sort by risk score descending
        path_risks.sort(key=lambda x: x["risk_score"], reverse=True)

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
        cvss_scores = [
            node.cvss for node in path.nodes
            if node.cvss is not None
        ]

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
            node.confidence for node in path.nodes
            if node.confidence is not None
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

    def _estimate_cvss(self, severity: str) -> float:
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
                path = Path(
                    nodes=[from_node, to_node],
                    edges=[edge]
                )
                paths.append(path)

        return paths
