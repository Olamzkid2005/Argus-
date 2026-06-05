"""Tests for llm_batch_service.py"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from orchestrator_pkg.analysis.llm_batch_service import LlmBatchService


class TestLlmBatchService:
    def test_init_stores_params_correctly(self):
        mock_client = MagicMock()
        save_poc = MagicMock()
        save_remediation = MagicMock()
        svc = LlmBatchService(
            llm_client=mock_client,
            engagement_id="eng-123",
            save_poc_fn=save_poc,
            save_remediation_fn=save_remediation,
        )
        assert svc.llm_client is mock_client
        assert svc.engagement_id == "eng-123"
        assert svc._save_poc is save_poc
        assert svc._save_remediation is save_remediation

    def test_generate_pocs_with_empty_scored_findings_returns_early(self):
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=MagicMock(),
        )
        result = svc.generate_pocs([], MagicMock(), MagicMock())
        assert result is None

    @patch("poc_generator.PoCGenerator")
    @patch("orchestrator_pkg.analysis.llm_batch_service.ThreadPoolExecutor")
    def test_generate_pocs_with_findings_uses_thread_pool_and_saves(
        self, MockPool, MockPoCGen
    ):
        mock_poc_gen = MagicMock()
        MockPoCGen.return_value = mock_poc_gen
        mock_future = MagicMock()
        mock_future.result.return_value = {"poc": "script"}
        mock_pool = MagicMock()
        mock_pool.__enter__.return_value = mock_pool
        mock_pool.submit.return_value = mock_future
        MockPool.return_value = mock_pool

        save_poc = MagicMock()
        save_poc.return_value = True
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=save_poc,
            save_remediation_fn=MagicMock(),
        )
        scored_findings = [{"id": "f1", "severity": "HIGH"}]
        llm_svc = MagicMock()
        cost_tracker = MagicMock()

        svc.generate_pocs(scored_findings, llm_svc, cost_tracker)

        MockPoCGen.assert_called_once_with(llm_client=svc.llm_client)
        MockPool.assert_called_once_with(max_workers=4)
        mock_pool.submit.assert_called_once_with(
            mock_poc_gen.generate, scored_findings[0], llm_svc, cost_tracker,
        )
        mock_future.result.assert_called_once_with(timeout=30)
        save_poc.assert_called_once_with("f1", {"poc": "script"})

    @patch("orchestrator_pkg.analysis.llm_batch_service.logger")
    @patch("poc_generator.PoCGenerator")
    def test_generate_pocs_catches_exceptions_gracefully(
        self, MockPoCGen, mock_logger
    ):
        MockPoCGen.side_effect = RuntimeError("batch failed")
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=MagicMock(),
        )
        svc.generate_pocs(
            [{"id": "f1"}], MagicMock(), MagicMock(),
        )
        mock_logger.warning.assert_called_once()
        assert "PoC generation batch failed" in mock_logger.warning.call_args[0][0]

    def test_generate_chain_exploits_without_cost_tracker_or_llm_svc_returns_early(self):
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=MagicMock(),
        )
        assert svc.generate_chain_exploits(None, MagicMock()) is None
        assert svc.generate_chain_exploits(MagicMock(), None) is None
        assert svc.generate_chain_exploits(None, None) is None

    @patch("chain_exploit_generator.ChainExploitGenerator")
    @patch("database.connection.get_db")
    def test_generate_chain_exploits_loads_attack_paths_and_generates(
        self, mock_get_db, MockChainGen
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [("ap1", "node1", 0.9, "CRITICAL")],
            [("f1", "xss", "/api", "evidence", True)],
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn
        mock_get_db.return_value = mock_db

        mock_chain_gen = MagicMock()
        mock_chain_gen.generate_for_engagement.return_value = [{"script": "exploit"}]
        MockChainGen.return_value = mock_chain_gen
        MockChainGen.save_scripts_to_db.return_value = 1

        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=MagicMock(),
        )
        llm_svc = MagicMock()
        cost_tracker = MagicMock()

        svc.generate_chain_exploits(llm_svc, cost_tracker)

        mock_chain_gen.generate_for_engagement.assert_called_once_with(
            engagement_id="eng-123",
            attack_paths=[
                {
                    "id": "ap1",
                    "path_nodes": "node1",
                    "risk_score": 0.9,
                    "normalized_severity": "CRITICAL",
                },
            ],
            findings_map={
                "f1": {
                    "id": "f1",
                    "type": "xss",
                    "endpoint": "/api",
                    "evidence": "evidence",
                    "poc_generated": True,
                },
            },
            llm_service=llm_svc,
            cost_tracker=cost_tracker,
            max_chains=3,
        )
        MockChainGen.save_scripts_to_db.assert_called_once_with(
            "eng-123", [{"script": "exploit"}],
        )

    def test_generate_fixes_without_cost_tracker_or_llm_svc_returns_early(self):
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=MagicMock(),
        )
        assert svc.generate_fixes([], None, None, None) is None
        assert svc.generate_fixes([], MagicMock(), None, MagicMock()) is None
        assert svc.generate_fixes([], MagicMock(), MagicMock(), None) is None

    @patch("developer_fix_assistant.DeveloperFixAssistant")
    @patch("orchestrator_pkg.analysis.llm_batch_service.ThreadPoolExecutor")
    def test_generate_fixes_with_findings_uses_thread_pool_and_saves(
        self, MockPool, MockFixAssistant
    ):
        mock_fix_assistant = MagicMock()
        MockFixAssistant.return_value = mock_fix_assistant
        mock_future = MagicMock()
        mock_future.result.return_value = {"fix": "patch"}
        mock_pool = MagicMock()
        mock_pool.__enter__.return_value = mock_pool
        mock_pool.submit.return_value = mock_future
        MockPool.return_value = mock_pool

        save_remediation = MagicMock()
        save_remediation.return_value = True
        svc = LlmBatchService(
            llm_client=MagicMock(),
            engagement_id="eng-123",
            save_poc_fn=MagicMock(),
            save_remediation_fn=save_remediation,
        )
        mock_recon_ctx = MagicMock()
        mock_recon_ctx.tech_stack = ["python", "react"]
        scored_findings = [{"id": "f1", "severity": "MEDIUM"}]
        llm_svc = MagicMock()
        cost_tracker = MagicMock()

        svc.generate_fixes(scored_findings, mock_recon_ctx, llm_svc, cost_tracker)

        MockFixAssistant.assert_called_once_with(llm_client=svc.llm_client)
        MockPool.assert_called_once_with(max_workers=4)
        mock_pool.submit.assert_called_once_with(
            mock_fix_assistant.generate,
            scored_findings[0],
            ["python", "react"],
            llm_svc,
            cost_tracker,
        )
        mock_future.result.assert_called_once_with(timeout=45)
        save_remediation.assert_called_once_with("f1", {"fix": "patch"})
