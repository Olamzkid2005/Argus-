"""
Tests for Attack Graph Engine
"""
import pytest

from attack_graph import AttackGraph, Edge, Node, Path, RelationshipType
from models.finding import Severity, VulnerabilityFinding


class TestRelationshipType:
    """Tests for RelationshipType enum"""

    def test_enum_values(self):
        """Test all enum values exist"""
        assert RelationshipType.CAUSES.value == "causes"
        assert RelationshipType.AMPLIFIES.value == "amplifies"
        assert RelationshipType.ENABLES.value == "enables"
        assert RelationshipType.DEPENDS_ON.value == "depends_on"
        assert RelationshipType.MITIGATES.value == "mitigates"
        assert RelationshipType.INDEPENDENT.value == "independent"

    def test_enum_is_str_enum(self):
        """Test RelationshipType is a StrEnum"""
        assert issubclass(RelationshipType, str)
        assert str(RelationshipType.CAUSES) == "causes"


class TestNodeNewFields:
    """Tests for Node new fields: prerequisites, downstream_impacts"""

    def test_default_prerequisites_empty(self):
        """Test that Node defaults to empty prerequisites list"""
        node = Node("n1", "vulnerability", {})
        assert node.prerequisites == []

    def test_default_downstream_impacts_empty(self):
        """Test that Node defaults to empty downstream_impacts list"""
        node = Node("n1", "vulnerability", {})
        assert node.downstream_impacts == []

    def test_custom_prerequisites(self):
        """Test that Node accepts custom prerequisites"""
        prereqs = ["user_interaction", "authenticated_session"]
        node = Node("n1", "vulnerability", {}, prerequisites=prereqs)
        assert node.prerequisites == prereqs

    def test_custom_downstream_impacts(self):
        """Test that Node accepts custom downstream_impacts"""
        impacts = ["session_theft", "credential_capture"]
        node = Node("n1", "vulnerability", {}, downstream_impacts=impacts)
        assert node.downstream_impacts == impacts


class TestEdgeNewFields:
    """Tests for Edge new field: relationship_type"""

    def test_default_relationship_independent(self):
        """Test that Edge defaults to INDEPENDENT relationship"""
        edge = Edge("n1", "n2", "test", 1.0)
        assert edge.relationship_type == RelationshipType.INDEPENDENT

    def test_custom_relationship(self):
        """Test that Edge accepts custom relationship_type"""
        edge = Edge("n1", "n2", "test", 1.0, relationship_type=RelationshipType.ENABLES)
        assert edge.relationship_type == RelationshipType.ENABLES


class TestPrereqAndImpactInference:
    """Tests for prerequisite and impact inference from finding type"""

    def test_ssrf_prerequisites(self):
        """Test SSRF prerequisites"""
        graph = AttackGraph("eng-123")
        prereqs = graph._infer_prerequisites("SSRF")
        assert "outbound_fetch_capability" in prereqs

    def test_xss_prerequisites(self):
        """Test XSS prerequisites"""
        graph = AttackGraph("eng-123")
        prereqs = graph._infer_prerequisites("XSS")
        assert "user_interaction" in prereqs
        assert "no_csp" in prereqs

    def test_unknown_type_returns_empty(self):
        """Test unknown finding type returns empty prerequisites"""
        graph = AttackGraph("eng-123")
        assert graph._infer_prerequisites("UNKNOWN_TYPE") == []

    def test_ssrf_downstream_impacts(self):
        """Test SSRF downstream impacts"""
        graph = AttackGraph("eng-123")
        impacts = graph._infer_downstream_impacts("SSRF")
        assert "credential_access" in impacts
        assert "internal_service_discovery" in impacts

    def test_rce_downstream_impacts(self):
        """Test RCE downstream impacts"""
        graph = AttackGraph("eng-123")
        impacts = graph._infer_downstream_impacts("RCE")
        assert "full_system_compromise" in impacts


class TestRelationshipInference:
    """Tests for relationship type inference from finding type"""

    def test_ssrf_is_enables(self):
        """Test SSRF is inferred as ENABLES"""
        graph = AttackGraph("eng-123")
        assert graph._infer_relationship("SSRF") == RelationshipType.ENABLES

    def test_rce_is_enables(self):
        """Test RCE is inferred as ENABLES"""
        graph = AttackGraph("eng-123")
        assert graph._infer_relationship("RCE") == RelationshipType.ENABLES

    def test_xss_is_amplifies(self):
        """Test XSS is inferred as AMPLIFIES"""
        graph = AttackGraph("eng-123")
        assert graph._infer_relationship("XSS") == RelationshipType.AMPLIFIES

    def test_csrf_is_amplifies(self):
        """Test CSRF is inferred as AMPLIFIES"""
        graph = AttackGraph("eng-123")
        assert graph._infer_relationship("CSRF") == RelationshipType.AMPLIFIES

    def test_info_is_independent(self):
        """Test INFO is inferred as INDEPENDENT"""
        graph = AttackGraph("eng-123")
        assert graph._infer_relationship("INFO") == RelationshipType.INDEPENDENT


class TestExploitability:
    """Tests for compute_exploitability"""

    def test_all_prerequisites_satisfied(self):
        """Test exploitability when all prereqs satisfied"""
        graph = AttackGraph("eng-123")
        node1 = Node("n1", "vulnerability", {}, prerequisites=["user_interaction", "no_csp"])
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        score = graph.compute_exploitability(path, {"user_interaction", "no_csp"})
        assert score == 1.0

    def test_no_prerequisites_satisfied(self):
        """Test exploitability when no prereqs satisfied"""
        graph = AttackGraph("eng-123")
        node1 = Node("n1", "vulnerability", {}, prerequisites=["user_interaction", "no_csp"])
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        score = graph.compute_exploitability(path, set())
        assert score == 0.0

    def test_some_prerequisites_satisfied(self):
        """Test exploitability when some prereqs satisfied"""
        graph = AttackGraph("eng-123")
        node1 = Node("n1", "vulnerability", {}, prerequisites=["user_interaction", "no_csp", "authenticated_session"])
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        score = graph.compute_exploitability(path, {"user_interaction", "authenticated_session"})
        assert score == pytest.approx(2.0 / 3.0)

    def test_no_prerequisites_returns_one(self):
        """Test exploitability is 1.0 when path has no prerequisites"""
        graph = AttackGraph("eng-123")
        node1 = Node("n1", "vulnerability", {})
        node2 = Node("n2", "endpoint", {})
        path = Path([node1, node2], [])

        score = graph.compute_exploitability(path, set())
        assert score == 1.0


class TestDownstreamPaths:
    """Tests for get_downstream_paths"""

    def test_downstream_from_vuln_node(self):
        """Test getting downstream paths from a vulnerability node"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="SSRF",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        vuln_node_id = "vuln_SSRF_https://example.com/api"
        downstream = graph.get_downstream_paths(vuln_node_id)

        assert len(downstream) >= 1

    def test_downstream_from_unknown_node(self):
        """Test getting downstream paths from unknown node returns empty"""
        graph = AttackGraph("eng-123")
        downstream = graph.get_downstream_paths("nonexistent")
        assert downstream == []

    def test_downstream_from_endpoint_node(self):
        """Test getting downstream paths from an endpoint node"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="XSS",
            severity=Severity.MEDIUM,
            confidence=0.7,
            endpoint="https://example.com/login",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        endpoint_node_id = "endpoint_https://example.com/login"
        downstream = graph.get_downstream_paths(endpoint_node_id)
        assert len(downstream) == 0  # No edges FROM endpoint


class TestSnapshotDict:
    """Tests for to_snapshot_dict"""

    def test_empty_graph(self):
        """Test snapshot dict from empty graph"""
        graph = AttackGraph("eng-123")
        snapshot = graph.to_snapshot_dict()
        assert "paths" in snapshot
        assert snapshot["paths"] == []

    def test_single_finding_snapshot(self):
        """Test snapshot dict with one finding"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        snapshot = graph.to_snapshot_dict()
        assert len(snapshot["paths"]) >= 1

        # Check first path has all required fields
        path0 = snapshot["paths"][0]
        assert "risk_score" in path0
        assert "nodes" in path0
        assert "edges" in path0

        # Check nodes have new fields
        for node in path0["nodes"]:
            assert "prerequisites" in node
            assert "downstream_impacts" in node

        # Check edges have new field
        for edge in path0["edges"]:
            assert "relationship_type" in edge


class TestAddFindingWiresNewFields:
    """Tests that add_finding wires prerequisites and impacts from maps"""

    def test_add_finding_sets_prerequisites(self):
        """Test add_finding sets prerequisites from PREREQ_MAP"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="IDOR",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/users",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        vuln_node_id = "vuln_IDOR_https://example.com/users"
        vuln_node = graph.nodes[vuln_node_id]
        assert "authenticated_session" in vuln_node.prerequisites
        assert "sequential_id" in vuln_node.prerequisites

    def test_add_finding_sets_downstream_impacts(self):
        """Test add_finding sets downstream_impacts from IMPACT_MAP"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="LFI",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/file",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        vuln_node_id = "vuln_LFI_https://example.com/file"
        vuln_node = graph.nodes[vuln_node_id]
        assert "file_disclosure" in vuln_node.downstream_impacts
        assert "rce_chainable" in vuln_node.downstream_impacts

    def test_add_finding_sets_relationship_type_on_edge(self):
        """Test add_finding sets relationship_type on edge"""
        graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="RCE",
            severity=Severity.CRITICAL,
            confidence=0.9,
            endpoint="https://example.com/exec",
            evidence={},
            source_tool="nuclei",
        )
        graph.add_finding(finding)

        edge = graph.edges[0]
        assert edge.relationship_type == RelationshipType.ENABLES


class TestStaticEstimateCvss:
    """Tests for _estimate_cvss as static method"""

    def test_called_as_static(self):
        """Test _estimate_cvss works as static method"""
        assert AttackGraph._estimate_cvss("CRITICAL") == 9.5
        assert AttackGraph._estimate_cvss("HIGH") == 7.5
        assert AttackGraph._estimate_cvss("UNKNOWN") == 5.0  # default

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
