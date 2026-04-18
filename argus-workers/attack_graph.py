"""
Attack Graph Engine - Computes probabilistic risk scores with confidence decay
"""
from typing import Dict, List, Optional
import math
from models.finding import VulnerabilityFinding


class Node:
    """Graph node representing vulnerability or endpoint"""
    
    def __init__(
        self,
        node_id: str,
        node_type: str,
        data: Dict,
        cvss: Optional[float] = None,
        confidence: Optional[float] = None
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
    
    def __init__(self, nodes: List[Node], edges: List[Edge]):
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
    
    def __init__(self, engagement_id: str):
        """
        Initialize Attack Graph
        
        Args:
            engagement_id: Engagement ID
        """
        self.engagement_id = engagement_id
        self.nodes = {}  # node_id -> Node
        self.edges = []  # List of edges
    
    def add_finding(self, finding: VulnerabilityFinding) -> None:
        """
        Add finding as vulnerability node
        
        Creates vulnerability node and endpoint node, connects them with edge.
        
        Args:
            finding: VulnerabilityFinding instance
        """
        # Create vulnerability node
        vuln_node_id = f"vuln_{finding.type}_{finding.endpoint}"
        if vuln_node_id in self.nodes:
            return

        vuln_node = Node(
            node_id=vuln_node_id,
            node_type="vulnerability",
            data={
                "type": finding.type,
                "severity": finding.severity.value if hasattr(finding.severity, 'value') else finding.severity,
                "endpoint": finding.endpoint,
                "source_tool": finding.source_tool,
            },
            cvss=finding.cvss_score or self._estimate_cvss(finding.severity.value if hasattr(finding.severity, 'value') else finding.severity),
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
    
    def attack_surface_weight(self, path: Path, exposure: str = "public") -> float:
        """
        Weight based on endpoint exposure
        
        Args:
            path: Attack path
            exposure: Exposure level
            
        Returns:
            Exposure factor
        """
        return self.EXPOSURE_FACTORS.get(exposure, 1.0)
    
    def get_all_paths(self) -> List[Path]:
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
    
    def get_highest_risk_paths(self, limit: int = 10) -> List[Dict]:
        """
        Get highest risk paths
        
        Args:
            limit: Maximum number of paths to return
            
        Returns:
            List of path dictionaries with risk scores
        """
        paths = self.get_all_paths()
        
        # Calculate risk for each path
        path_risks = []
        for path in paths:
            risk = self.compute_risk(path)
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
