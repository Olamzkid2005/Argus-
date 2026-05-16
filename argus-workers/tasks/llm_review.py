"""
Celery task for post-scan LLM response analysis.

Runs after the scan phase completes. Loads low-confidence findings,
replays HTTP requests, has the LLM analyze responses, and updates
findings with LLM-verified results.

Respects budget limits and gracefully degrades when LLM is unavailable.
"""
import contextlib
import logging
import os

from celery_app import app

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies at module load time
_llm_client = None
_llm_detector = None
_finding_repo = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        try:
            from llm_client import LLMClient
            _llm_client = LLMClient()
        except ImportError as e:
            logger.warning(f"LLMClient not available: {e}")
            _llm_client = None
    return _llm_client


def _get_llm_detector():
    global _llm_detector
    if _llm_detector is None:
        try:
            from tools.llm_detector import LLMDetector
            client = _get_llm_client()
            if client and client.is_available():
                from config.constants import LLM_RESPONSE_ANALYSIS_MODEL
                _llm_detector = LLMDetector(
                    llm_client=client,
                    model=LLM_RESPONSE_ANALYSIS_MODEL,
                )
        except ImportError as e:
            logger.warning(f"LLMDetector not available (import error): {e}")
            _llm_detector = None
        except Exception as e:
            logger.warning(f"LLMDetector not available: {type(e).__name__}: {e}")
            _llm_detector = None
    return _llm_detector


def _get_finding_repo(db_conn_string: str):
    global _finding_repo
    if _finding_repo is None:
        try:
            from database.repositories.finding_repository import FindingRepository
            _finding_repo = FindingRepository(db_conn_string)
        except Exception as e:
            logger.warning(f"FindingRepository not available: {e}")
            _finding_repo = None
    return _finding_repo


@app.task(bind=True, name="tasks.llm_review.run_llm_review")
def run_llm_review(self, engagement_id: str, budget: dict = None, trace_id: str = None):
    """
    Post-scan LLM review task.

    Analyzes low-confidence findings with LLM to detect subtle vulnerabilities.
    Respects engagement budget. Gracefully degrades on failure.

    Args:
        engagement_id: Engagement ID
        budget: Budget configuration dict (max_cycles, max_depth)
        trace_id: Optional trace ID for distributed tracing
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("llm_review", engagement_id=engagement_id)
    slog.phase_header("LLM REVIEW")

    db_conn_string = os.getenv("DATABASE_URL")

    # Check if LLM review is enabled
    try:
        from config.constants import (
            llm_review_confidence_threshold,
            llm_review_max_per_engagement,
            llm_review_max_response_chars,
            llm_review_min_confidence,
        )
    except ImportError:
        llm_review_confidence_threshold = 0.7
        llm_review_min_confidence = 0.3
        llm_review_max_per_engagement = 20
        llm_review_max_response_chars = 3000

    # Load feature flag dynamically from Redis (set via UI Settings page)
    try:
        from llm_client import load_llm_setting
        llm_review_enabled = load_llm_setting("llm_review_enabled", "true") == "true"
    except ImportError:
        llm_review_enabled = True

    if not llm_review_enabled:
        slog.info("LLM review disabled via config")
        return {"status": "skipped", "reason": "LLM_REVIEW_ENABLED=False"}

    # Load live replay setting once to avoid per-finding Redis lookups
    try:
        live_replay_enabled = load_llm_setting("llm_review_live_replay", "false") == "true"
    except Exception:
        live_replay_enabled = False

    # Get LLM detector
    detector = _get_llm_detector()
    if not detector:
        slog.info("LLM detector not available, skipping LLM review")
        return {"status": "skipped", "reason": "LLM detector unavailable"}

    # Get finding repository
    repo = _get_finding_repo(db_conn_string)
    if not repo:
        slog.warning("Finding repository not available, skipping LLM review")
        return {"status": "skipped", "reason": "Finding repository unavailable"}

    # Initialize budget manager
    budget_manager = None
    try:
        from loop_budget_manager import LoopBudgetManager
        budget_manager = LoopBudgetManager(engagement_id, budget or {})
    except Exception as e:
        slog.warning(f"Budget manager not available: {e}")

    # Load candidate findings
    try:
        candidate_findings = repo.find_unreviewed_low_confidence(
            engagement_id=engagement_id,
            threshold=llm_review_confidence_threshold,
            min_confidence=llm_review_min_confidence,
            limit=llm_review_max_per_engagement,
        )
    except Exception as e:
        slog.error(f"Failed to load candidate findings: {e}")
        return {"status": "error", "error": str(e)}

    if not candidate_findings:
        slog.info("No candidate findings for LLM review")
        return {"status": "completed", "analyzed": 0, "total": 0}

    slog.info(f"LLM review: {len(candidate_findings)} candidate findings")

    # Analyze each finding
    analyzed_count = 0
    confirmed_count = 0

    for finding in candidate_findings:
        if budget_manager:
            can_continue, _ = budget_manager.can_continue({"type": "llm_review"})
            if not can_continue:
                slog.info("LLM review budget exhausted — stopping")
                break
            budget_manager.consume({"type": "llm_review"})

        slog.tool_start("LLM Review", [f"finding={finding.get('id', '?')[:8]}..."])

        try:
            # Skip if finding has no payload/response evidence
            evidence = finding.get("evidence", {})
            payload = evidence.get("payload", "")

            # Replay HTTP request to get fresh response
            response = _replay_request(finding.get("endpoint", ""), evidence, live_replay_enabled)
            if not response:
                slog.tool_result("LLM Review", f"Skipping finding {finding.get('id', '?')[:8]}: no response")
                continue

            # Skip if detector says skip
            if detector.should_skip(finding, response):
                slog.tool_result("LLM Review", f"Skipping finding {finding.get('id', '?')[:8]}: should_skip=True")
                continue

            # LLM analysis
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Already in an event loop — cannot run_until_complete on a
                # running loop. Use create_task + wait instead.
                future = asyncio.ensure_future(detector.analyze_async(
                    test_url=finding.get("endpoint", ""),
                    vuln_class=finding.get("type", "UNKNOWN"),
                    payload=payload,
                    response=response,
                    max_response_chars=llm_review_max_response_chars,
                ))
                loop.run_until_complete(asyncio.wait([future]))
                result = future.result()
            else:
                result = asyncio.run(detector.analyze_async(
                    test_url=finding.get("endpoint", ""),
                    vuln_class=finding.get("type", "UNKNOWN"),
                    payload=payload,
                    response=response,
                    max_response_chars=llm_review_max_response_chars,
                ))

            if result is None:
                slog.tool_result("LLM Review", f"Returned None for finding {finding.get('id', '?')[:8]}")
                # Still mark as reviewed to avoid re-analyzing
                with contextlib.suppress(Exception):
                    repo.add_llm_evidence(finding["id"], {"error": "LLM returned no result"})
                continue

            analyzed_count += 1

            # If LLM confirmed vulnerability with higher confidence
            llm_confirmed = result.vulnerable and result.confidence > 0.5
            current_confidence = finding.get("confidence", 0.0)

            # Store LLM evidence
            llm_data = {
                "vulnerable": result.vulnerable,
                "confidence": result.confidence,
                "evidence_quote": result.evidence_quote,
                "vuln_type": result.vuln_type,
                "reasoning": result.reasoning,
                "model": result.model,
                "timestamp": result.timestamp,
            }

            try:
                repo.add_llm_evidence(finding["id"], llm_data)
            except Exception as e:
                logger.warning(f"Failed to store LLM evidence: {e}")

            # If LLM confirms with higher confidence, update the finding
            if llm_confirmed and result.confidence > float(current_confidence):
                new_confidence = min(1.0, float(current_confidence) + result.confidence * 0.3)
                try:
                    repo.update_confidence(finding["id"], new_confidence)
                    confirmed_count += 1
                    slog.tool_result("LLM Review", f"Confirmed {finding.get('type')} at {finding.get('endpoint')}: confidence {current_confidence:.2f} -> {new_confidence:.2f}")
                except Exception as e:
                    logger.warning(f"Failed to update confidence: {e}")

        except Exception as e:
            slog.warning(f"LLM review failed for finding {finding.get('id', '?')[:8]}: {e}")
            continue

    # LLM review uses its own budget (llm_review_max_per_engagement cap),
    # not the intelligence engine's recon_expand cycles.
    budget_was_exhausted = False
    slog.info(f"LLM review complete: {analyzed_count} analyzed, {confirmed_count} confirmed, {'budget exhausted' if budget_was_exhausted else 'all candidates processed'}")

    return {
        "status": "completed",
        "analyzed": analyzed_count,
        "confirmed": confirmed_count,
        "total_candidates": len(candidate_findings),
        "budget_exhausted": budget_was_exhausted,
    }


def _replay_request(endpoint: str, evidence: dict, live_replay_enabled: bool = False):
    """
    Replay an HTTP request to get a fresh response for analysis.

    Requires LLM_REVIEW_LIVE_REPLAY to be explicitly enabled.
    Falls back to stored evidence if disabled or on failure.

    Args:
        endpoint: Target URL
        evidence: Finding evidence dict (may contain payload, request, response)
        live_replay_enabled: Pre-loaded feature flag to avoid per-call Redis lookup

    Returns:
        Response object or None on failure
    """
    if not live_replay_enabled:
        logger.debug("Live replay disabled — using stored evidence for endpoint %s", endpoint)
        return None

    try:
        from urllib.parse import urlencode

        import requests

        headers = {"User-Agent": "Argus-LLM-Review/1.0"}
        timeout = 15

        payload = evidence.get("payload", "")
        if payload and payload.strip():
            test_url = f"{endpoint}?{urlencode({'q': payload})}"
            resp = requests.get(test_url, headers=headers, timeout=timeout, allow_redirects=True)
        else:
            # No payload — still try to GET the endpoint for analysis
            # This covers EXPOSED_SECRET, SERVER_INFO_DISCLOSURE, etc.
            resp = requests.get(endpoint, headers=headers, timeout=timeout, allow_redirects=True)

        return resp

    except Exception as e:
        logger.debug(f"Request replay failed for {endpoint}: {e}")
        return None
