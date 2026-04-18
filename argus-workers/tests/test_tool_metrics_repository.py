"""
Tests for Tool Metrics Repository

Requirements: 22.1, 22.2
"""
import pytest
import os
import sys
from datetime import datetime, timedelta
import uuid

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.repositories.tool_metrics_repository import ToolMetricsRepository


@pytest.fixture
def metrics_repository():
    """Create a metrics repository with test database"""
    # Use test database connection string
    connection_string = os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
    return ToolMetricsRepository(connection_string)


class TestToolMetricsRepository:
    """Test suite for ToolMetricsRepository"""
    
    def test_record_metric_stores_data(self, metrics_repository):
        """Test that record_metric stores metric data correctly"""
        # This test requires a database connection
        # Skip if no test database is available
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        metric_id = metrics_repository.record_metric(
            tool_name="nuclei",
            duration_ms=1500,
            success=True
        )
        
        assert metric_id is not None
        assert isinstance(metric_id, str)
    
    def test_record_metric_with_failure(self, metrics_repository):
        """Test that record_metric stores failure correctly"""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        metric_id = metrics_repository.record_metric(
            tool_name="httpx",
            duration_ms=500,
            success=False
        )
        
        assert metric_id is not None
    
    def test_get_performance_stats_returns_data(self, metrics_repository):
        """Test that get_performance_stats returns statistics"""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        # Record some test metrics
        metrics_repository.record_metric("test_tool_1", 100, True)
        metrics_repository.record_metric("test_tool_1", 200, True)
        metrics_repository.record_metric("test_tool_1", 300, False)
        
        # Get stats
        stats = metrics_repository.get_performance_stats(days=1)
        
        assert isinstance(stats, list)
        # Should have at least one tool
        assert len(stats) >= 1
    
    def test_get_tool_stats_for_specific_tool(self, metrics_repository):
        """Test that get_tool_stats returns stats for a specific tool"""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        # Record some test metrics
        metrics_repository.record_metric("specific_test_tool", 100, True)
        metrics_repository.record_metric("specific_test_tool", 200, True)
        
        # Get stats for specific tool
        stats = metrics_repository.get_tool_stats("specific_test_tool", days=1)
        
        if stats:
            assert stats["tool_name"] == "specific_test_tool"
            assert stats["total_executions"] >= 2
            assert "avg_duration_ms" in stats
            assert "success_rate" in stats
    
    def test_get_recent_executions_returns_limited_results(self, metrics_repository):
        """Test that get_recent_executions respects limit"""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        # Record some test metrics
        for i in range(5):
            metrics_repository.record_metric("limit_test_tool", 100 + i * 10, True)
        
        # Get recent executions with limit
        executions = metrics_repository.get_recent_executions("limit_test_tool", limit=3)
        
        assert len(executions) <= 3
    
    def test_performance_stats_calculates_correctly(self, metrics_repository):
        """Test that performance statistics are calculated correctly"""
        if not os.getenv("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set")
        
        import random
        tool_name = f"calc_test_tool_{random.randint(1000, 9999)}"
        
        # Record metrics with known values
        metrics_repository.record_metric(tool_name, 100, True)
        metrics_repository.record_metric(tool_name, 200, True)
        metrics_repository.record_metric(tool_name, 300, False)
        
        # Get stats
        stats = metrics_repository.get_tool_stats(tool_name, days=1)
        
        if stats:
            # Check total executions
            assert stats["total_executions"] == 3
            
            # Check success count
            assert stats["success_count"] == 2
            
            # Check average duration (100 + 200 + 300) / 3 = 200
            assert float(stats["avg_duration_ms"]) == 200.0
            
            # Check success rate (2/3 * 100 = 66.67)
            assert float(stats["success_rate"]) == pytest.approx(66.67, rel=0.1)


class TestToolMetricsRepositoryUnit:
    """Unit tests that don't require database"""
    
    def test_repository_has_correct_table_name(self):
        """Test that repository has correct table name"""
        repo = ToolMetricsRepository("postgresql://localhost/test")
        assert repo.table_name == "tool_metrics"
    
    def test_repository_has_correct_id_column(self):
        """Test that repository has correct ID column"""
        repo = ToolMetricsRepository("postgresql://localhost/test")
        assert repo.id_column == "id"
