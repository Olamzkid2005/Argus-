"""
Tests for Attack Graph Engine
"""
from attack_graph import AttackGraph, Node, Path
from models.finding import Severity, VulnerabilityFinding


class TestAttackGraph:
    """Test suite for AttackGraph"""

    def setup_method(self):
        """Setup test fixtures"""
        self.graph = AttackGraph("eng-123")

    def test_add_finding_creates_nodes(self):
        """Test that add_finding creates vulnerability and endpoint nodes"""
        finding = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei"
        )

        self.graph.add_finding(finding)

        assert len(self.graph.nodes) == 2  # vuln + endpoint
        assert len(self.graph.edges) == 1

    def test_add_finding_reuses_endpoint_node(self):
        """Test that add_finding reuses existing endpoint nodes"""
        finding1 = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei"
        )
        finding2 = VulnerabilityFinding(
            type="XSS",
            severity=Severity.MEDIUM,
            confidence=0.7,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei"
        )

        self.graph.add_finding(finding1)
        self.graph.add_finding(finding2)

        # 2 vuln nodes + 1 shared endpoint node = 3 total
        assert len(self.graph.nodes) == 3
        assert len(self.graph.edges) == 2

    def test_estimate_cvss_from_severity(self):
        """Test CVSS estimation from severity"""
        assert self.graph._estimate_cvss("CRITICAL") == 9.5
        assert self.graph._estimate_cvss("HIGH") == 7.5
        assert self.graph._estimate_cvss("MEDIUM") == 5.0
        assert self.graph._estimate_cvss("LOW") == 3.0
        assert self.graph._estimate_cvss("INFO") == 0.0

    def test_calculate_base_risk(self):
        """Test base risk calculation (average CVSS)"""
        node1 = Node("n1", "vulnerability", {}, cvss=8.0, confidence=0.9)
        node2 = Node("n2", "vulnerability", {}, cvss=6.0, confidence=0.8)
        path = Path([node1, node2], [])

        base_risk = self.graph._calculate_base_risk(path)

        assert base_risk == 7.0  # (8.0 + 6.0) / 2

    def test_compute_confidence_decay_geometric_mean(self):
        """Test confidence decay using geometric mean"""
        node1 = Node("n1", "vulnerability", {}, cvss=8.0, confidence=0.9)
        node2 = Node("n2", "vulnerability", {}, cvss=6.0, confidence=0.8)
        path = Path([node1, node2], [])

        confidence_weight = self.graph.compute_confidence_decay(path)

        # Geometric mean: (0.9 * 0.8)^(1/2) = 0.72^0.5 = 0.8485
        assert 0.84 <= confidence_weight <= 0.85

    def test_calculate_chain_multiplier(self):
        """Test chain multiplier calculation"""
        node1 = Node("n1", "vulnerability", {}, cvss=8.0)
        node2 = Node("n2", "vulnerability", {}, cvss=6.0)
        node3 = Node("n3", "endpoint", {})

        path_length_1 = Path([node1], [])
        path_length_2 = Path([node1, node2], [])
        path_length_3 = Path([node1, node2, node3], [])

        assert self.graph._calculate_chain_multiplier(path_length_1) == 1.0
        assert self.graph._calculate_chain_multiplier(path_length_2) == 1.2
        assert self.graph._calculate_chain_multiplier(path_length_3) == 1.4

    def test_exposure_factors(self):
        """Test exposure factor values"""
        assert self.graph.EXPOSURE_FACTORS["public"] == 1.0
        assert self.graph.EXPOSURE_FACTORS["authenticated"] == 0.7
        assert self.graph.EXPOSURE_FACTORS["internal"] == 0.4

    def test_compute_risk_formula(self):
        """Test complete risk computation formula"""
        node1 = Node("n1", "vulnerability", {}, cvss=8.0, confidence=0.9)
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        risk = self.graph.compute_risk(path, exposure="public")

        # base_risk=8.0, confidence_weight=0.9, chain_multiplier=1.2, exposure=1.0
        # risk = 8.0 * 0.9 * 1.2 * 1.0 = 8.64
        assert 8.6 <= risk <= 8.7

    def test_compute_risk_normalized_to_max_10(self):
        """Test that risk is normalized to max 10.0"""
        node1 = Node("n1", "vulnerability", {}, cvss=10.0, confidence=1.0)
        node2 = Node("n2", "vulnerability", {}, cvss=10.0, confidence=1.0)
        node3 = Node("n3", "vulnerability", {}, cvss=10.0, confidence=1.0)
        path = Path([node1, node2, node3], [])

        risk = self.graph.compute_risk(path, exposure="public")

        assert risk <= 10.0

    def test_compute_risk_with_authenticated_exposure(self):
        """Test risk computation with authenticated exposure"""
        node1 = Node("n1", "vulnerability", {}, cvss=8.0, confidence=0.9)
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        risk_public = self.graph.compute_risk(path, exposure="public")
        risk_auth = self.graph.compute_risk(path, exposure="authenticated")

        # Authenticated should be 70% of public
        assert risk_auth < risk_public
        assert abs(risk_auth - (risk_public * 0.7)) < 0.1

    def test_get_all_paths_returns_paths(self):
        """Test get_all_paths returns list of paths"""
        finding = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei"
        )

        self.graph.add_finding(finding)
        paths = self.graph.get_all_paths()

        assert len(paths) == 1
        assert len(paths[0].nodes) == 2

    def test_get_highest_risk_paths_sorts_by_risk(self):
        """Test get_highest_risk_paths sorts by risk score"""
        finding1 = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.CRITICAL,
            confidence=0.9,
            endpoint="https://example.com/api1",
            evidence={},
            source_tool="nuclei",
            cvss_score=9.5
        )
        finding2 = VulnerabilityFinding(
            type="XSS",
            severity=Severity.MEDIUM,
            confidence=0.7,
            endpoint="https://example.com/api2",
            evidence={},
            source_tool="nuclei",
            cvss_score=5.0
        )

        self.graph.add_finding(finding1)
        self.graph.add_finding(finding2)

        paths = self.graph.get_highest_risk_paths()

        assert len(paths) == 2
        assert paths[0]["risk_score"] > paths[1]["risk_score"]
