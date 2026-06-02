"""
Tests for AttackGraphRepository persistence layer
"""
from unittest.mock import MagicMock, patch

import pytest

from attack_graph import AttackGraph, RelationshipType
from attack_graph_db import AttackGraphRepository
from models.finding import Severity, VulnerabilityFinding


class TestAttackGraphRepository:
    """Test suite for AttackGraphRepository"""

    def setup_method(self):
        """Setup test fixtures"""
        self.repo = AttackGraphRepository("postgresql://localhost/test")
        self.graph = AttackGraph("eng-123")
        finding = VulnerabilityFinding(
            type="SQL_INJECTION",
            severity=Severity.HIGH,
            confidence=0.8,
            endpoint="https://example.com/api",
            evidence={},
            source_tool="nuclei",
        )
        self.graph.add_finding(finding)
        finding2 = VulnerabilityFinding(
            type="XSS",
            severity=Severity.MEDIUM,
            confidence=0.7,
            endpoint="https://example.com/login",
            evidence={},
            source_tool="nuclei",
        )
        self.graph.add_finding(finding2)

    def test_save_paths_calls_sql(self):
        """Test save_paths executes correct SQL statements"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            saved = self.repo.save_paths("eng-123", self.graph)

        # Verify DELETE — occurs after the SELECT for chain_exploit_script preservation
        delete_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "DELETE FROM attack_paths" in call[0][0]
        ]
        assert len(delete_calls) >= 1, "Expected at least one DELETE FROM attack_paths call"

        # Verify INSERT calls
        insert_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO attack_paths" in call[0][0]
        ]
        assert len(insert_calls) >= 1

        # Verify commit was called
        assert mock_conn.commit.called
        assert saved >= 1

    def test_save_paths_empty_graph(self):
        """Test save_paths with empty graph saves 0 paths"""
        empty_graph = AttackGraph("eng-456")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            saved = self.repo.save_paths("eng-456", empty_graph)

        assert saved == 0

    def test_save_paths_rollback_on_error(self):
        """Test save_paths rolls back on error"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("DB error")

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            with pytest.raises(Exception):
                self.repo.save_paths("eng-123", self.graph)

        assert mock_conn.rollback.called

    def test_load_graph_reconstructs_nodes_and_edges(self):
        """Test load_graph reconstructs graph from stored data"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Simulate DB rows
        mock_cursor.fetchall.return_value = [
            ({
                "nodes": [
                    {
                        "id": "vuln_SQL_INJECTION_https://example.com/api",
                        "type": "vulnerability",
                        "data": {
                            "type": "SQL_INJECTION",
                            "severity": "HIGH",
                            "endpoint": "https://example.com/api",
                            "source_tool": "nuclei",
                        },
                        "cvss": 7.5,
                        "confidence": 0.8,
                        "prerequisites": ["parametrized_query_bypassed"],
                        "downstream_impacts": ["data_exfiltration", "auth_bypass"],
                    },
                    {
                        "id": "endpoint_https://example.com/api",
                        "type": "endpoint",
                        "data": {"url": "https://example.com/api"},
                        "cvss": None,
                        "confidence": None,
                        "prerequisites": [],
                        "downstream_impacts": [],
                    },
                ],
                "edges": [
                    {
                        "from_node": "vuln_SQL_INJECTION_https://example.com/api",
                        "to_node": "endpoint_https://example.com/api",
                        "type": "independent",
                        "correlation_factor": 1.0,
                        "relationship_type": "enables",
                    },
                ],
            }, 7.5),
        ]

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            loaded = self.repo.load_graph("eng-123")

        assert loaded is not None
        assert loaded.engagement_id == "eng-123"
        assert len(loaded.nodes) >= 2
        assert len(loaded.edges) >= 1

        # Check node fields preserved
        vuln_id = "vuln_SQL_INJECTION_https://example.com/api"
        assert vuln_id in loaded.nodes
        vuln_node = loaded.nodes[vuln_id]
        assert "parametrized_query_bypassed" in vuln_node.prerequisites
        assert "data_exfiltration" in vuln_node.downstream_impacts

        # Check edge relationship_type preserved
        edge = loaded.edges[0]
        assert edge.relationship_type == RelationshipType.ENABLES

    def test_load_graph_no_paths(self):
        """Test load_graph returns None when no paths exist"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            loaded = self.repo.load_graph("eng-missing")

        assert loaded is None

    def test_load_graph_returns_none_on_error(self):
        """Test load_graph returns None on DB error"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.side_effect = Exception("DB error")

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            loaded = self.repo.load_graph("eng-123")

        assert loaded is None

    def test_delete_for_engagement(self):
        """Test delete_for_engagement executes correct SQL"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 3

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            result = self.repo.delete_for_engagement("eng-123")

        assert result is True
        delete_call = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM attack_paths" in delete_call
        assert mock_conn.commit.called

    def test_delete_for_engagement_no_rows(self):
        """Test delete_for_engagement returns False when no rows deleted"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.rowcount = 0

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            result = self.repo.delete_for_engagement("eng-123")

        assert result is False

    def test_delete_for_engagement_returns_false_on_error(self):
        """Test delete_for_engagement returns False on error"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("DB error")

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            result = self.repo.delete_for_engagement("eng-123")

        assert result is False

    def test_count_paths(self):
        """Test count_paths returns count"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = [5]

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            count = self.repo.count_paths("eng-123")

        assert count == 5

    def test_count_paths_returns_zero_on_error(self):
        """Test count_paths returns 0 on error"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("DB error")

        with patch.object(self.repo, '_get_connection', return_value=mock_conn):
            count = self.repo.count_paths("eng-123")

        assert count == 0

    def test_risk_to_normalized_severity_clamps(self):
        """Test _risk_to_normalized_severity clamps to 0-10"""
        assert AttackGraphRepository._risk_to_normalized_severity(-1.0) == 0.0
        assert AttackGraphRepository._risk_to_normalized_severity(0.0) == 0.0
        assert AttackGraphRepository._risk_to_normalized_severity(5.5) == 5.5
        assert AttackGraphRepository._risk_to_normalized_severity(10.0) == 10.0
        assert AttackGraphRepository._risk_to_normalized_severity(15.0) == 10.0
