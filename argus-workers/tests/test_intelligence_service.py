"""Tests for intelligence_service.py"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from orchestrator_pkg.analysis.intelligence_service import IntelligenceService


class TestIntelligenceService:
    def test_init_stores_params_correctly(self):
        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client="mock_client",
        )
        assert svc.db_conn == "db://conn"
        assert svc.engagement_id == "eng-123"
        assert svc.llm_client == "mock_client"

    @patch("intelligence_engine.IntelligenceEngine")
    def test_evaluate_creates_intelligence_engine_and_calls_evaluate(self, MockEngine):
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = {"result": "ok"}
        MockEngine.return_value = mock_engine

        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client=None,
        )
        snapshot = {"key": "val"}
        result = svc.evaluate(snapshot, org_id="org-1")

        MockEngine.assert_called_once_with("db://conn")
        mock_engine.evaluate.assert_called_once_with(snapshot, org_id="org-1")
        assert result == {"result": "ok"}

    @patch("config.constants.LLM_MAX_COST_PER_ENGAGEMENT", "unused")
    @patch("tasks.utils.LlmCostTracker")
    @patch("llm_service.LLMService")
    @patch("tasks.utils.load_recon_context")
    @patch("llm_synthesizer.LLMSynthesizer")
    def test_run_synthesis_with_available_llm_client(
        self,
        MockSynthesizer,
        mock_load_recon,
        MockLLMService,
        MockCostTracker,
    ):
        mock_tracker = MagicMock()
        MockCostTracker.return_value = mock_tracker
        mock_llm_svc = MagicMock()
        MockLLMService.return_value = mock_llm_svc
        mock_recon = MagicMock()
        mock_load_recon.return_value = mock_recon
        mock_synth = MagicMock()
        mock_synth.synthesize.return_value = {"summary": "synthesized"}
        MockSynthesizer.return_value = mock_synth

        mock_llm_client = MagicMock()
        mock_llm_client.is_available.return_value = True

        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client=mock_llm_client,
        )
        evaluation = {"scored_findings": [{"id": "f1"}]}
        snapshot = {"attack_graph": {"paths": [{"id": "p1"}]}}
        result = svc.run_synthesis(evaluation, snapshot)

        MockCostTracker.assert_called_once_with(
            engagement_id="eng-123",
            max_cost="unused",
        )
        MockLLMService.assert_called_once_with(
            mock_llm_client,
            cost_tracker=mock_tracker,
        )
        mock_load_recon.assert_called_once_with("eng-123")
        MockSynthesizer.assert_called_once_with(mock_llm_svc)
        mock_synth.synthesize.assert_called_once_with(
            scored_findings=[{"id": "f1"}],
            attack_paths=[{"id": "p1"}],
            recon_context=mock_recon,
        )

        synthesis, llm_svc, cost_tracker, recon_ctx, scored = result
        assert synthesis == {"summary": "synthesized"}
        assert llm_svc is mock_llm_svc
        assert cost_tracker is mock_tracker
        assert recon_ctx is mock_recon
        assert scored == [{"id": "f1"}]

    @patch("tasks.utils.LlmCostTracker")
    def test_run_synthesis_with_unavailable_llm_client_returns_empty(
        self, MockCostTracker
    ):
        mock_llm_client = MagicMock()
        mock_llm_client.is_available.return_value = False

        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client=mock_llm_client,
        )
        evaluation = {"scored_findings": [{"id": "f1"}]}
        snapshot = {}
        result = svc.run_synthesis(evaluation, snapshot)

        MockCostTracker.assert_called_once()
        synthesis, llm_svc, cost_tracker, recon_ctx, scored = result
        assert synthesis == {}
        assert llm_svc is None
        assert scored == [{"id": "f1"}]

    @patch("orchestrator_pkg.analysis.intelligence_service.logger")
    @patch("tasks.utils.LlmCostTracker")
    @patch("tasks.utils.load_recon_context")
    @patch("llm_service.LLMService")
    def test_run_synthesis_when_llm_init_fails_returns_gracefully(
        self, MockLLMService, mock_load_recon, MockCostTracker, mock_logger
    ):
        MockLLMService.side_effect = ValueError("init failed")
        mock_llm_client = MagicMock()
        mock_llm_client.is_available.return_value = True

        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client=mock_llm_client,
        )
        evaluation = {"scored_findings": [{"id": "f1"}]}
        snapshot = {}
        result = svc.run_synthesis(evaluation, snapshot)

        mock_logger.warning.assert_called_once()
        assert "LLM service init failed" in mock_logger.warning.call_args[0][0]

        synthesis, llm_svc, cost_tracker, recon_ctx, scored = result
        assert synthesis == {}
        assert llm_svc is None
        assert scored == [{"id": "f1"}]

    @patch("orchestrator_pkg.analysis.intelligence_service.logger")
    @patch("tasks.utils.LlmCostTracker")
    @patch("llm_service.LLMService")
    @patch("tasks.utils.load_recon_context")
    @patch("llm_synthesizer.LLMSynthesizer")
    def test_run_synthesis_when_synthesis_fails_returns_gracefully_with_scored_findings(
        self,
        MockSynthesizer,
        mock_load_recon,
        MockLLMService,
        MockCostTracker,
        mock_logger,
    ):
        mock_llm_client = MagicMock()
        mock_llm_client.is_available.return_value = True

        mock_llm_svc = MagicMock()
        MockLLMService.return_value = mock_llm_svc
        mock_load_recon.return_value = MagicMock()

        mock_synth = MagicMock()
        mock_synth.synthesize.side_effect = RuntimeError("synthesis failed")
        MockSynthesizer.return_value = mock_synth

        svc = IntelligenceService(
            db_conn="db://conn",
            engagement_id="eng-123",
            llm_client=mock_llm_client,
        )
        evaluation = {"scored_findings": [{"id": "f1"}]}
        snapshot = {}
        result = svc.run_synthesis(evaluation, snapshot)

        mock_logger.warning.assert_called_once()
        assert "LLM synthesis failed" in mock_logger.warning.call_args[0][0]

        synthesis, llm_svc, cost_tracker, recon_ctx, scored = result
        assert synthesis == {}
        assert llm_svc is mock_llm_svc
        assert scored == [{"id": "f1"}]
