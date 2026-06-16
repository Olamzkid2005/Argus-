"""
scripts/smoke_test.py

Standalone smoke test for the Argus workers core engine.

Validates that all core modules:
  1. Import without errors
  2. Can instantiate key classes (with mocked infrastructure where needed)
  3. Core methods produce expected outputs

This test requires NO infrastructure — no Redis, PostgreSQL, security tools,
or LLM API keys. If any of those are needed, they are either mocked,
gracefully degraded, or caught as expected failures.

Usage:
    cd argus-workers && python scripts/smoke_test.py
    cd argus-workers && python scripts/smoke_test.py --verbose   # show details per check
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

# Allow running from the repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Test infrastructure ───────────────────────────────────────────────────

PASSED = 0
FAILED = 0
SKIPPED = 0


def _section(name: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")


def _check(label: str, cond: bool, detail: str = "", verbose: bool = False) -> bool:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        icon = "  \u2705"
        if verbose and detail:
            print(f"{icon}  {label}  \u2014  {detail}")
        elif verbose:
            print(f"{icon}  {label}")
        return True
    else:
        FAILED += 1
        print(f"  \u274c  {label}")
        if detail:
            print(f"       {detail}")
        return False


def _skip(label: str) -> None:
    global SKIPPED
    SKIPPED += 1
    print(f"  \u23ed  {label}")


def _header(label: str) -> None:
    print(f"\n  \u2014\u2014 {label} \u2014\u2014")


# ── 1. Environment & Config ───────────────────────────────────────────────

def test_config_constants() -> bool:
    """Validate that named constants load correctly."""
    from config.constants import (
        GIT_HOST_ALLOWLIST,
        HARD_TIMEOUT_SECONDS,
        LLM_AGENT_MAX_COST_USD,
        MAX_TOOL_RETRIES,
        TOOL_TIMEOUT_DEFAULT,
    )
    ok = True
    _header("config.constants")
    ok &= _check("HARD_TIMEOUT_SECONDS == 7200", HARD_TIMEOUT_SECONDS == 7200)
    ok &= _check("TOOL_TIMEOUT_DEFAULT == 180", TOOL_TIMEOUT_DEFAULT == 180)
    ok &= _check("MAX_TOOL_RETRIES == 2", MAX_TOOL_RETRIES == 2)
    ok &= _check("LLM_AGENT_MAX_COST_USD is float", isinstance(LLM_AGENT_MAX_COST_USD, float))
    ok &= _check("GIT_HOST_ALLOWLIST includes github.com", "github.com" in GIT_HOST_ALLOWLIST)
    return ok


def test_config_redis() -> bool:
    """Validate Redis config defaults gracefully."""
    _header("config.redis")
    from config.redis import REDIS_URL
    return _check("REDIS_URL defaults to redis://localhost:6379",
                  REDIS_URL == "redis://localhost:6379")


def test_feature_flags() -> bool:
    """Validate feature flags system works without DB."""
    _header("feature_flags")
    from feature_flags import FeatureFlags, get_flag, is_enabled

    fresh_flags = FeatureFlags()
    ok = True
    ok &= _check("FeatureFlags instantiated", True)
    ok &= _check("is_enabled with no flag returns default",
                 fresh_flags.is_enabled("TEST_FLAG_A", default=False) is False)
    ok &= _check("get_flag with no flag returns default on fresh instance",
                 fresh_flags.get_flag("TEST_FLAG_B", default=42) == 42)
    ok &= _check("is_enabled with True default",
                 fresh_flags.is_enabled("TEST_FLAG_C", default=True) is True)
    ok &= _check("clear_cache works", fresh_flags.clear_cache() is None)

    # Module-level convenience functions
    ok &= _check("module-level is_enabled returns default",
                 is_enabled("MODULE_FLAG_A", default=False) is False)
    ok &= _check("module-level get_flag returns default",
                 get_flag("MODULE_FLAG_B", default=99) == 99)
    return ok


# ── 2. Core Data Models ──────────────────────────────────────────────────

def test_models() -> bool:
    """Validate core data models."""
    _header("models.finding")
    from models.finding import Severity, VulnerabilityFinding

    ok = True
    ok &= _check("Severity.CRITICAL exists", Severity.CRITICAL.value == "CRITICAL")
    ok &= _check("Severity.HIGH exists", Severity.HIGH.value == "HIGH")

    finding = VulnerabilityFinding(
        type="XSS",
        severity=Severity.HIGH,
        confidence=0.85,
        endpoint="https://example.com",
        evidence={"payload": "<script>alert(1)</script>"},
        source_tool="nuclei",
        cvss_score=7.5,
    )
    ok &= _check("VulnerabilityFinding created", finding.type == "XSS")
    ok &= _check("Finding has severity", finding.severity == Severity.HIGH)
    ok &= _check("Finding has cvss_score", finding.cvss_score == 7.5)
    ok &= _check("Finding model_dump works", isinstance(finding.model_dump(), dict))

    _header("models.confidence_scorer")
    from models.confidence_scorer import ConfidenceScorer
    score = ConfidenceScorer.compute(0.85, 0.9, 0.2)
    ok &= _check("ConfidenceScorer.compute returns float 0..1",
                 0 <= score <= 1)
    ok &= _check("ConfidenceScorer - high agreement + high evidence = high",
                 score > 0.5)

    _header("models.recon_context")
    from models.recon_context import ReconContext
    ctx = ReconContext(
        target_url="https://example.com",
        scan_type="webapp",
        tech_stack=["python", "flask"],
    )
    ok &= _check("ReconContext created", ctx.target_url == "https://example.com")
    ok &= _check("ReconContext tech_stack", "python" in ctx.tech_stack)
    ok &= _check("ReconContext to_dict", isinstance(ctx.to_dict(), dict))

    _header("models.candidate_list")
    from models.candidate_list import Candidate, CandidateList, CandidateSource
    cl = CandidateList(target="https://example.com/login")
    ok &= _check("CandidateList created", cl is not None)
    ok &= _check("CandidateList has no candidates by default", len(cl.candidates) == 0)
    c = Candidate(endpoint="/api", source=CandidateSource.NUCLEI_CVE,
                  vuln_slug="cve-2024-test", snippet="test")
    cl.candidates.append(c)
    ok &= _check("Candidate added to list", len(cl.candidates) == 1)
    ok &= _check("Candidate has endpoint", c.endpoint == "/api")
    ok &= _check("Candidate has source", c.source == CandidateSource.NUCLEI_CVE)
    summary = cl.to_llm_summary()
    ok &= _check("to_llm_summary returns non-empty string", len(summary) > 10)

    return ok


# ── 3. State Machine ──────────────────────────────────────────────────────

def test_state_machine() -> bool:
    """Validate state machine transitions without DB."""
    _header("state_machine")
    from state_machine import EngagementStateMachine

    ok = True
    ok &= _check("STATES include all expected states",
                 set(EngagementStateMachine.STATES) >= {
                     "created", "recon", "scanning", "analyzing",
                     "reporting", "complete", "failed", "paused"})
    ok &= _check("TRANSITIONS from created",
                 "recon" in EngagementStateMachine.TRANSITIONS["created"])
    ok &= _check("complete has no transitions",
                 EngagementStateMachine.TRANSITIONS["complete"] == [])

    eid = str(uuid.uuid4())
    machine = EngagementStateMachine(eid, current_state="created")
    ok &= _check("EngagementStateMachine created", machine.current_state == "created")
    ok &= _check("can_transition_to('recon') is True", machine.can_transition_to("recon"))
    ok &= _check("can_transition_to('complete') is False (from created)",
                 not machine.can_transition_to("complete"))
    ok &= _check("get_valid_transitions returns list",
                 isinstance(machine.get_valid_transitions(), list))
    ok &= _check("get_valid_transitions from created",
                 machine.get_valid_transitions() == ["recon", "failed", "paused"])

    terminal = EngagementStateMachine(eid, current_state="complete")
    ok &= _check("Terminal state complete has no transitions",
                 terminal.get_valid_transitions() == [])

    paused = EngagementStateMachine(eid, current_state="paused")
    ok &= _check("Paused can resume to recon", paused.can_transition_to("recon"))
    ok &= _check("Paused can resume to scanning", paused.can_transition_to("scanning"))

    try:
        EngagementStateMachine(eid, current_state="nonexistent")
        ok &= _check("Invalid state raises ValueError", False)
    except ValueError as e:
        ok &= _check("Invalid state raises ValueError",
                     "Invalid" in str(e))

    return ok


# ── 4. Intelligence Engine ────────────────────────────────────────────────

def test_intelligence_engine() -> bool:
    """Validate intelligence engine scoring and analysis."""
    _header("intelligence_engine")
    from intelligence_engine import IntelligenceEngine

    ok = True
    engine = IntelligenceEngine()
    ok &= _check("IntelligenceEngine instantiated", engine is not None)
    ok &= _check("QUALITY_ORDER exists", len(engine.QUALITY_ORDER) == 3)

    # Evidence strength
    ok &= _check("Verified evidence strength = 1.0",
                 engine._get_evidence_strength({"evidence_strength": "VERIFIED"}) == 1.0)
    ok &= _check("Minimal evidence strength = 0.6",
                 engine._get_evidence_strength({"evidence_strength": "MINIMAL"}) == 0.6)
    ok &= _check("Missing evidence defaults to 0.6",
                 engine._get_evidence_strength({}) == 0.6)

    # Tool agreement
    ok &= _check("Two-tool agreement = 0.85",
                 engine._calculate_tool_agreement([
                     {"source_tool": "nuclei"}, {"source_tool": "dalfox"}]) == 0.85)
    ok &= _check("Three+ tool agreement = 1.0",
                 engine._calculate_tool_agreement([
                     {"source_tool": "nuclei"}, {"source_tool": "dalfox"},
                     {"source_tool": "sqlmap"}]) == 1.0)

    # Agreement level strings
    ok &= _check("_get_agreement_level(1) = single_tool",
                 engine._get_agreement_level(1) == "single_tool")
    ok &= _check("_get_agreement_level(2) = medium",
                 engine._get_agreement_level(2) == "medium")
    ok &= _check("_get_agreement_level(3) = high",
                 engine._get_agreement_level(3) == "high")

    # Grouping
    groups = engine._group_findings_for_agreement([
        {"type": "XSS", "endpoint": "https://example.com/search"},
        {"type": "REFLECTED_XSS", "endpoint": "https://example.com/search"},
        {"type": "SQL_INJECTION", "endpoint": "https://example.com/api"},
    ])
    ok &= _check("_group_findings_for_agreement returns dict",
                 isinstance(groups, dict))
    xss_key = [k for k in groups if "XSS" in k][0]
    ok &= _check("XSS findings grouped by family", len(groups[xss_key]) == 2)

    # CVE extraction
    cves = engine._extract_cve_ids({
        "type": "VULNERABLE_COMPONENT",
        "evidence": {"details": "CVE-2024-12345 and CVE-2024-67890"}
    })
    ok &= _check("_extract_cve_ids finds CVEs",
                 "CVE-2024-12345" in cves and "CVE-2024-67890" in cves)
    ok &= _check("_extract_cve_ids returns empty when no matches",
                 engine._extract_cve_ids({"type": "SQLI", "evidence": {}}) == [])
    ok &= _check("_extract_cve_ids limits to 5",
                 len(engine._extract_cve_ids({
                     "type": "", "evidence": {
                         "details": " ".join([f"CVE-2021-{1000+i}" for i in range(10)])}
                 })) <= 5)

    # Threat feed matching
    feed_hits = engine._check_threat_feeds({
        "type": "SQL_INJECTION", "endpoint": "https://example.com/api"
    })
    ok &= _check("SQL injection triggers exploitdb feed", len(feed_hits) >= 1)
    if feed_hits:
        ok &= _check("Feed hit has expected keys",
                     all(k in feed_hits[0] for k in ("feed", "risk", "description")))

    # False positive detection
    fp_result = engine._detect_false_positive({
        "evidence": {"detail": "x" * 600},
        "source_tool": "nuclei",
        "tool_agreement_level": "high",
        "endpoint": "https://example.com/api",
        "severity": "HIGH",
        "type": "SQL_INJECTION",
    })
    ok &= _check("FP detection returns dict with verdict",
                 "verdict" in fp_result and "confidence" in fp_result)
    ok &= _check("Rich evidence yields true_positive",
                 fp_result["verdict"] in ("true_positive", "likely_true_positive"))
    ok &= _check("FP confidence is float 0..1", 0 <= fp_result["confidence"] <= 1)

    # Risk calculation
    ok &= _check("3 critical -> risk=critical",
                 engine._calculate_overall_risk([{"severity": "CRITICAL"}] * 3) == "critical")
    ok &= _check("3 high -> risk=high",
                 engine._calculate_overall_risk([{"severity": "HIGH"}] * 3) == "high")
    ok &= _check("3 medium -> risk=medium",
                 engine._calculate_overall_risk([{"severity": "MEDIUM"}] * 3) == "medium")
    ok &= _check("1 info -> risk=low",
                 engine._calculate_overall_risk([{"severity": "INFO"}]) == "low")

    return ok


# ── 5. Attack Graph ───────────────────────────────────────────────────────

def test_attack_graph() -> bool:
    """Validate attack graph construction without DB."""
    _header("attack_graph")
    from attack_graph import AttackGraph
    from models.finding import Severity, VulnerabilityFinding

    ok = True
    eid = str(uuid.uuid4())
    graph = AttackGraph(eid)
    ok &= _check("AttackGraph instantiated", graph is not None)
    ok &= _check("AttackGraph has engagement_id", graph.engagement_id == eid)
    ok &= _check("AttackGraph starts with empty nodes", len(graph.nodes) == 0)

    finding = VulnerabilityFinding(
        type="XSS",
        severity=Severity.HIGH,
        confidence=0.85,
        endpoint="https://example.com/search",
        evidence={"payload": "<script>"},
        source_tool="nuclei",
    )
    graph.add_finding(finding)
    ok &= _check("add_finding adds a vuln node",
                 any(n.type == "vulnerability" for n in graph.nodes.values()))
    ok &= _check("add_finding adds an endpoint node",
                 any(n.type == "endpoint" for n in graph.nodes.values()))

    snapshot = graph.to_snapshot_dict()
    ok &= _check("to_snapshot_dict returns dict", isinstance(snapshot, dict))
    ok &= _check("Snapshot has paths key", "paths" in snapshot)
    ok &= _check("Snapshot paths is a list", isinstance(snapshot["paths"], list))
    ok &= _check("Snapshot has at least one path", len(snapshot["paths"]) >= 1)

    chains = graph.find_chains()
    ok &= _check("find_chains returns list", isinstance(chains, list))

    all_paths = graph.get_all_paths()
    ok &= _check("get_all_paths returns list", isinstance(all_paths, list))

    paths_with_chains = graph.get_all_paths_with_chains()
    ok &= _check("get_all_paths_with_chains returns list", isinstance(paths_with_chains, list))

    downstream = graph.get_downstream_paths([n for n in graph.nodes if graph.nodes[n].type == "vulnerability"][0])
    ok &= _check("get_downstream_paths returns list", isinstance(downstream, list))

    highest_risk = graph.get_highest_risk_paths(limit=5)
    ok &= _check("get_highest_risk_paths returns list", isinstance(highest_risk, list))
    if highest_risk:
        ok &= _check("Risk score is a number",
                     isinstance(highest_risk[0].get("risk_score"), (int, float)))

    return ok


# ── 6. Tool Definitions ──────────────────────────────────────────────────

def test_tool_definitions() -> bool:
    """Validate tool definitions registry."""
    _header("tool_definitions")
    from tool_definitions import ALL_PHASES, TOOLS, SignalQuality, get_tool

    ok = True
    ok &= _check("TOOLS registry is populated", len(TOOLS) > 10)
    ok &= _check("nuclei in registry", "nuclei" in TOOLS)
    ok &= _check("nuclei has CONFIRMED signal",
                 TOOLS["nuclei"].signal_quality == SignalQuality.CONFIRMED)

    nuclei = get_tool("nuclei")
    ok &= _check("get_tool('nuclei') returns definition", nuclei is not None)
    if nuclei:
        ok &= _check("nuclei has timeout", nuclei.timeout == 600)
        ok &= _check("nuclei phases include scan", "scan" in nuclei.phases)

    ok &= _check("get_tool('nonexistent') returns None",
                 get_tool("nonexistent_tool_xyz") is None)
    ok &= _check("ALL_PHASES defined", len(ALL_PHASES) >= 5)
    ok &= _check("nuclei is CONFIRMED",
                 TOOLS["nuclei"].signal_quality == SignalQuality.CONFIRMED)
    ok &= _check("dalfox is PROBABLE",
                 TOOLS["dalfox"].signal_quality == SignalQuality.PROBABLE)
    ok &= _check("ffuf is CANDIDATE",
                 TOOLS["ffuf"].signal_quality == SignalQuality.CANDIDATE)

    return ok


# ── 7. Tool Registry (Agent) ──────────────────────────────────────────────

def test_tool_registry() -> bool:
    """Validate agent tool registry."""
    _header("agent.tool_registry")
    from agent.agent_result import AgentResult
    from agent.tool_registry import ToolRegistry

    ok = True
    registry = ToolRegistry()
    ok &= _check("ToolRegistry instantiated", registry is not None)

    def echo(text: str = "") -> AgentResult:
        return AgentResult(tool="echo", success=True, output=text)

    registry.register("echo", echo, {
        "name": "echo",
        "description": "Echo back the input",
        "parameters": [{"name": "text", "description": "Text to echo", "required": True}],
    })
    ok &= _check("Tool registered", registry.get_tool("echo") is not None)
    ok &= _check("list_tools returns list", len(registry.list_tools()) == 1)

    result = registry.call("echo", text="hello")
    ok &= _check("Tool call succeeds", result.success is True)
    ok &= _check("Tool call returns output", result.output == "hello")
    ok &= _check("Result has duration_ms", result.duration_ms is not None)

    unknown = registry.call("nonexistent")
    ok &= _check("Unknown tool returns error", unknown.success is False)
    ok &= _check("Unknown tool has error message", "Unknown tool" in unknown.error)

    return ok


# ── 8. Results & Validation Utilities ──────────────────────────────────────

def test_utils() -> bool:
    """Validate utility modules."""
    _header("utils")

    ok = True
    from utils.result import Err, Ok, is_err, is_ok
    ok_result = Ok(42)
    ok &= _check("Ok result created", is_ok(ok_result) and ok_result.value == 42)
    err_result = Err("something went wrong")
    ok &= _check("Err result created", is_err(err_result))
    ok &= _check("Err result error value", "wrong" in err_result.error)

    from utils.validation import validate_uuid
    valid_uuid = str(uuid.uuid4())
    ok &= _check("validate_uuid accepts valid UUID",
                 validate_uuid(valid_uuid, "test") == valid_uuid)
    try:
        validate_uuid("not-a-uuid", "test")
        ok &= _check("validate_uuid rejects invalid UUID", False)
    except ValueError:
        ok &= _check("validate_uuid rejects invalid UUID", True)

    from utils.retry import retry, retry_function
    ok &= _check("retry imported", callable(retry))
    ok &= _check("retry_function imported", callable(retry_function))

    return ok


def test_sanitization() -> bool:
    """Validate sanitization utilities."""
    _header("utils.sanitization")
    from utils.sanitization import (
        check_for_dangerous_content,
        sanitize_evidence,
        sanitize_string,
        strip_dangerous_tags,
    )

    ok = True
    ok &= _check("sanitize_string escapes HTML",
                 sanitize_string("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;")

    evidence = sanitize_evidence({"payload": "<script>alert(1)</script>"})
    ok &= _check("sanitize_evidence escapes HTML in dict",
                 evidence.get("payload") == "&lt;script&gt;alert(1)&lt;/script&gt;")

    dangerous = check_for_dangerous_content("<script>alert(1)</script>")
    ok &= _check("check_for_dangerous_content finds script tags", len(dangerous) > 0)

    stripped = strip_dangerous_tags("<script>alert(1)</script>")
    ok &= _check("strip_dangerous_tags removes script tags", "[removed]" in stripped)
    return ok


# ── 9. Error Classifier ──────────────────────────────────────────────────

def test_error_classifier() -> bool:
    """Validate error classification."""
    _header("error_classifier")
    from error_classifier import (
        ErrorCategory,
        ErrorCode,
        classify_by_error_code,
        classify_error,
        tag_error,
    )

    ok = True
    trans = classify_error(ConnectionError("connection reset"))
    ok &= _check("Connection reset -> TRANSIENT",
                 trans.category == ErrorCategory.TRANSIENT)
    ok &= _check("Transient error should retry", trans.should_retry is True)

    rate = classify_error(Exception("429 Too Many Requests"))
    ok &= _check("429 -> RATE_LIMIT", rate.category == ErrorCategory.RATE_LIMIT)

    perm = classify_error(FileNotFoundError("config not found"))
    # classify_error may categorize as UNKNOWN due to no matching pattern,
    # but should_retry should be False because "not found" is a permanent indicator
    ok &= _check("Not found -> should NOT retry", perm.should_retry is False)
    ok &= _check("Not found -> retry_delay is 0", perm.retry_delay_seconds == 0)

    unk = classify_error(Exception("something unexpected"))
    ok &= _check("Unknown error -> UNKNOWN", unk.category == ErrorCategory.UNKNOWN)

    code_result = classify_by_error_code(ErrorCode.RATE_LIMITED)
    ok &= _check("ErrorCode RATE_LIMITED -> RATE_LIMIT",
                 code_result.category == ErrorCategory.RATE_LIMIT)

    code_result2 = classify_by_error_code(ErrorCode.FILE_NOT_FOUND)
    ok &= _check("ErrorCode FILE_NOT_FOUND -> PERMANENT",
                 code_result2.category == ErrorCategory.PERMANENT)

    exc = Exception("test error")
    tagged = tag_error(exc, ErrorCode.DATABASE_ERROR)
    ok &= _check("tag_error attaches error_code attribute",
                 getattr(tagged, "error_code", None) == ErrorCode.DATABASE_ERROR)

    return ok


# ── 10. Cache ────────────────────────────────────────────────────────────

def test_cache() -> bool:
    """Validate cache module instantiates (even without Redis)."""
    _header("cache")
    from cache import WorkerCache, cache, cached

    ok = True
    worker_cache = WorkerCache(ttl=60)
    ok &= _check("WorkerCache instantiated", worker_cache is not None)
    ok &= _check("TTL_SHORT == 60", WorkerCache.TTL_SHORT == 60)
    ok &= _check("TTL_LONG == 3600", WorkerCache.TTL_LONG == 3600)
    ok &= _check("Global cache instance exists", cache is not None)

    @cached(key_prefix="smoke_test", ttl=30)
    def my_func(x: int) -> int:
        return x * 2

    result = my_func(21)
    ok &= _check("cached decorator returns correct value", result == 42)
    ok &= _check("cached decorator has invalidate helper",
                 hasattr(my_func, "cache_invalidate") and callable(my_func.cache_invalidate))

    return ok


# ── 11. LLM Client ───────────────────────────────────────────────────────

def test_llm_client() -> bool:
    """Validate LLM client imports and configuration (no API key needed)."""
    _header("llm_client")
    from config.constants import LLM_AGENT_MODEL
    from llm_client import LLMClient

    ok = True
    ok &= _check("LLM_AGENT_MODEL from config", isinstance(LLM_AGENT_MODEL, str))
    ok &= _check("LLM_AGENT_MODEL non-empty", len(LLM_AGENT_MODEL) > 0)

    client = LLMClient()
    ok &= _check("LLMClient instantiated", client is not None)
    # is_available() depends on API keys in environment — not asserted here.
    # The test only checks that the client instantiates without error.
    ok &= _check("LLMClient instantiated without error", True)

    return ok


def test_llm_service() -> bool:
    """Validate LLM service imports and basic setup."""
    _header("llm_service")
    from llm_client import LLMClient
    from llm_service import LLMService

    ok = True
    # LLMService requires an llm_client argument
    ok &= _check("LLMService class imported", LLMService is not None)

    client = LLMClient()
    service = LLMService(llm_client=client)
    ok &= _check("LLMService instantiated with client", service is not None)
    ok &= _check("LLMService is_available() == client state",
                 service.is_available() == client.is_available())
    return ok


# ── 12. Pipeline Router & Dispatch ───────────────────────────────────────

def test_pipeline() -> bool:
    """Validate pipeline routing imports."""
    _header("pipeline_router & dispatch_task")
    from dispatch_task import dispatch_task
    from pipeline_router import execute_recon_pipeline, execute_scan_pipeline

    ok = True
    ok &= _check("execute_recon_pipeline imported", callable(execute_recon_pipeline))
    ok &= _check("execute_scan_pipeline imported", callable(execute_scan_pipeline))
    ok &= _check("dispatch_task imported", callable(dispatch_task))

    return ok


# ── 13. Tracing ──────────────────────────────────────────────────────────

def test_tracing() -> bool:
    """Validate tracing imports and basic instantiation."""
    _header("tracing")
    from tracing import ExecutionSpan, StructuredLogger, get_trace_id

    ok = True
    ok &= _check("StructuredLogger imported", StructuredLogger is not None)
    ok &= _check("ExecutionSpan imported", ExecutionSpan is not None)
    ok &= _check("get_trace_id imported", callable(get_trace_id))

    trace_id = get_trace_id()
    # Without an ExecutionContext set (no infrastructure), get_trace_id returns None
    # which is expected — trace context is only set during active engagements.
    ok &= _check("get_trace_id returns None or string without context",
                 trace_id is None or isinstance(trace_id, str))

    return ok


# ── 14. CVSS Calculator ──────────────────────────────────────────────────

def test_cvss() -> bool:
    """Validate CVSS estimator."""
    _header("cvss_calculator")
    from cvss_calculator import TYPE_BASE_SCORES, estimate_cvss, get_cvss_label

    ok = True
    ok &= _check("estimate_cvss imported", callable(estimate_cvss))
    ok &= _check("SQL_INJECTION base score = 9.8", TYPE_BASE_SCORES.get("SQL_INJECTION") == 9.8)
    ok &= _check("XSS base score = 6.1", TYPE_BASE_SCORES.get("XSS") == 6.1)

    # Test estimate_cvss with various inputs
    score = estimate_cvss("SQL_INJECTION", "CRITICAL", "verified")
    ok &= _check("SQL_INJECTION + CRITICAL + verified = 9.8",
                 score == 9.8)
    ok &= _check("estimate_cvss returns float 0..10", 0 <= score <= 10)

    # Test label function
    ok &= _check("get_cvss_label(True) = CVSS (NVD)",
                 get_cvss_label(has_cve=True) == "CVSS (NVD)")
    ok &= _check("get_cvss_label(False) = Estimated CVSS",
                 get_cvss_label(has_cve=False) == "Estimated CVSS")

    return ok


# ── 15. ReAct Agent ──────────────────────────────────────────────────────

def test_react_agent() -> bool:
    """Validate ReAct agent setup (without LLM)."""
    _header("agent.react_agent")
    from agent.react_agent import ReActAgent
    from agent.tool_registry import ToolRegistry

    ok = True
    registry = ToolRegistry()
    agent = ReActAgent(registry=registry)
    ok &= _check("ReActAgent instantiated", agent is not None)
    ok &= _check("Agent has valid max_iterations", agent.max_iterations > 0)
    ok &= _check("Agent has phase", hasattr(agent, "_phase"))

    ok &= _check("can_transition_to 'analyze' from 'scan'",
                 agent.can_transition_to("analyze"))
    ok &= _check("transition_to works", agent.transition_to("analyze") is True)
    ok &= _check("Phase updated after transition", agent._phase == "analyze")
    ok &= _check("invalid transition returns False",
                 agent.transition_to("nonexistent") is False)

    ReActAgent._ensure_phase_tools()
    ok &= _check("PHASE_TOOLS loaded", len(ReActAgent.PHASE_TOOLS) > 0)
    ok &= _check("recon tools defined", "recon" in ReActAgent.PHASE_TOOLS)
    ok &= _check("PHASE_AGENTS defined", len(ReActAgent.PHASE_AGENTS) > 0)
    ok &= _check("scan phase description exists",
                 "Scan" in ReActAgent.PHASE_AGENTS.get("scan", {}).get("description", ""))

    return ok


# ── 16. Dead Letter Queue ────────────────────────────────────────────────

def test_dlq() -> bool:
    """Validate dead letter queue imports."""
    _header("dead_letter_queue")
    from dead_letter_queue import DeadLetterQueue

    dlq = DeadLetterQueue()
    ok = True
    ok &= _check("DeadLetterQueue instantiated", dlq is not None)
    ok &= _check("DLQ has MAX_DLQ_SIZE", dlq.MAX_DLQ_SIZE == 1000)
    return ok


# ── 17. Checkpoint Manager ───────────────────────────────────────────────

def test_checkpoint() -> bool:
    """Validate checkpoint manager instantiation (no DB)."""
    _header("checkpoint_manager")
    from checkpoint_manager import CheckpointContext, CheckpointManager

    mgr = CheckpointManager()
    ok = True
    ok &= _check("CheckpointManager instantiated", mgr is not None)

    ctx = CheckpointContext(mgr, str(uuid.uuid4()), "scan")
    ok &= _check("CheckpointContext instantiated", ctx is not None)
    ok &= _check("CheckpointContext has add_result",
                 hasattr(ctx, "add_result") and callable(ctx.add_result))

    return ok


# ── 18. Scan Diff Engine ─────────────────────────────────────────────────

def test_scan_diff() -> bool:
    """Validate scan diff engine imports."""
    _header("scan_diff_engine")
    from scan_diff_engine import ScanDiffEngine

    sde = ScanDiffEngine()
    ok = True
    ok &= _check("ScanDiffEngine instantiated", sde is not None)
    return ok


# ── 19. Auth Components ──────────────────────────────────────────────────

def test_auth() -> bool:
    """Validate auth component imports."""
    _header("agent.auth modules")
    from agent.auth_context import AuthContext

    ok = True
    ctx = AuthContext()
    ok &= _check("AuthContext instantiated", ctx is not None)
    ok &= _check("AuthContext not authenticated by default",
                 ctx.is_authenticated() is False)
    return ok


# ── 20. Streaming ─────────────────────────────────────────────────────────

def test_streaming() -> bool:
    """Validate streaming module imports."""
    _header("streaming")
    from streaming import EventBus, StreamManager, emit_thinking

    ok = True
    ok &= _check("StreamManager imported", StreamManager is not None)
    ok &= _check("EventBus imported", EventBus is not None)
    ok &= _check("emit_thinking imported", callable(emit_thinking))
    return ok


# ── Runner ───────────────────────────────────────────────────────────────

def main(verbose: bool = False) -> int:
    global PASSED, FAILED, SKIPPED

    print(f"\n{'#' * 70}")
    print("  ARGUS WORKERS \u2014\u2014 CORE ENGINE SMOKE TEST")
    print("  No infrastructure required (no Redis, PostgreSQL, tools, or API keys)")
    print(f"{'#' * 70}")
    print(f"\n  Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    _section("1. ENVIRONMENT & CONFIG")
    test_config_constants()
    test_config_redis()
    test_feature_flags()

    _section("2. CORE DATA MODELS")
    test_models()

    _section("3. STATE MACHINE (core engine)")
    test_state_machine()

    _section("4. INTELLIGENCE ENGINE (core engine)")
    test_intelligence_engine()

    _section("5. ATTACK GRAPH (core engine)")
    test_attack_graph()

    _section("6. TOOL DEFINITIONS REGISTRY")
    test_tool_definitions()

    _section("7. AGENT TOOL REGISTRY")
    test_tool_registry()

    _section("8. UTILITIES (Result, Validation, Retry)")
    test_utils()
    test_sanitization()

    _section("9. ERROR CLASSIFIER")
    test_error_classifier()

    _section("10. CACHE")
    test_cache()

    _section("11. LLM CLIENT & SERVICE")
    test_llm_client()
    test_llm_service()

    _section("12. PIPELINE ROUTER & DISPATCH")
    test_pipeline()

    _section("13. TRACING")
    test_tracing()

    _section("14. CVSS CALCULATOR")
    test_cvss()

    _section("15. REACT AGENT")
    test_react_agent()

    _section("16. DEAD LETTER QUEUE")
    test_dlq()

    _section("17. CHECKPOINT MANAGER")
    test_checkpoint()

    _section("18. SCAN DIFF ENGINE")
    test_scan_diff()

    _section("19. AUTH COMPONENTS")
    test_auth()

    _section("20. STREAMING")
    test_streaming()

    total = PASSED + FAILED + SKIPPED
    print(f"\n{'=' * 70}")
    print(f"  RESULTS:  {PASSED} passed  |  {FAILED} failed  |  "
          f"{SKIPPED} skipped  |  {total} total checks")
    print(f"{'=' * 70}")

    if FAILED == 0:
        print("\n  \u2705  ALL CORE ENGINE CHECKS PASSED")
        print("      The backend is ready for validation with infrastructure tests.")
        return 0
    else:
        print(f"\n  \u274c  {FAILED} CHECK(S) FAILED")
        print("      Review the failures above before proceeding to infrastructure tests.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Argus Workers \u2014\u2014 Core Engine Smoke Test"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show individual check details (default: show only failures)",
    )
    args = parser.parse_args()
    sys.exit(main(verbose=args.verbose))
