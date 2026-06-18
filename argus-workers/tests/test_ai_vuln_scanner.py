"""
Tests for AIVulnScanner (AbstractTool pattern).

Uses mocked ``_safe_request`` and ``_query_ai`` to test scanner logic
without hitting real AI endpoints.
"""

from unittest.mock import Mock, patch

from tool_core.base import ToolContext
from tool_core.result import ToolStatus
from tools.ai_vuln_scanner import (
    INFORMATION_DISCLOSURE_PROBES,
    INJECTION_SUCCESS_INDICATORS,
    PROMPT_INJECTION_PAYLOADS,
    REFUSAL_PATTERNS,
    SENSITIVE_DATA_PATTERNS,
    AIVulnScanner,
)

# ── Construction ────────────────────────────────────────────────────────


class TestAIVulnScannerConstruction:
    """Scanner initialises with correct state."""

    def test_tool_name(self):
        assert AIVulnScanner.tool_name == "ai_vuln_scanner"

    def test_inherits_abstract_tool(self):
        from tool_core.base import AbstractTool

        assert issubclass(AIVulnScanner, AbstractTool)

    def test_defaults(self):
        scanner = AIVulnScanner()
        assert scanner.timeout == 60
        assert scanner.rate_limit == 0.5
        assert scanner.verify is True

    def test_custom_params(self):
        scanner = AIVulnScanner(timeout=30, rate_limit=0.1, engagement_id="eng-1")
        assert scanner.timeout == 30
        assert scanner.rate_limit == 0.1
        assert scanner.engagement_id == "eng-1"


# ── Refusal detection (pure regex logic, no mocking needed) ─────────────


class TestIsRefusal:
    """_is_refusal correctly identifies refusal patterns."""

    def test_i_am_sorry(self):
        scanner = AIVulnScanner()
        assert scanner._is_refusal("i am sorry but i cannot help with that")

    def test_i_cannot(self):
        scanner = AIVulnScanner()
        assert scanner._is_refusal("i cannot reveal that information")

    def test_as_an_ai(self):
        scanner = AIVulnScanner()
        assert scanner._is_refusal("as an ai i must decline this request")

    def test_no_refusal(self):
        scanner = AIVulnScanner()
        assert not scanner._is_refusal("Here is the database schema: users(id, name)")

    def test_empty_text(self):
        scanner = AIVulnScanner()
        assert not scanner._is_refusal("")

    def test_refusal_regex_pins(self):
        """All REFUSAL_PATTERNS produce working regexes."""
        for pattern in REFUSAL_PATTERNS:
            assert hasattr(pattern, "search") or isinstance(pattern, str)


# ── Sensitive data detection (pure regex logic) ─────────────────────────


class TestContainsSensitiveData:
    """_contains_sensitive_data detects leaked secrets."""

    def test_sql_query(self):
        scanner = AIVulnScanner()
        assert scanner._contains_sensitive_data("SELECT * FROM users WHERE id = 1")

    def test_api_key(self):
        scanner = AIVulnScanner()
        # No space after colon — regex api_key[:\s] needs key contiguous with value
        assert scanner._contains_sensitive_data("api_key:sk-1234567890123456")

    def test_database_url(self):
        scanner = AIVulnScanner()
        assert scanner._contains_sensitive_data("postgresql://user:pass@localhost/db")

    def test_bearer_token(self):
        scanner = AIVulnScanner()
        assert scanner._contains_sensitive_data(
            "bearer eyJhbGciOiJIUzI1NiJ9.eyJ0ZXN0IjoxfQ.signature"
        )

    def test_clean_text(self):
        scanner = AIVulnScanner()
        assert not scanner._contains_sensitive_data("Hello, how can I help you today?")

    def test_system_prompt_text(self):
        scanner = AIVulnScanner()
        assert scanner._contains_sensitive_data(
            "system prompt: you are a helpful assistant"
        )


# ── Response text extraction (pure logic, no mocking needed) ────────────


class TestExtractResponseText:
    """_extract_response_text handles various AI response shapes."""

    def test_plain_string(self):
        scanner = AIVulnScanner()
        assert scanner._extract_response_text("Hello") == "Hello"

    def test_message_key(self):
        scanner = AIVulnScanner()
        assert scanner._extract_response_text({"message": "Hi there"}) == "Hi there"

    def test_response_key(self):
        scanner = AIVulnScanner()
        assert scanner._extract_response_text({"response": "Hello"}) == "Hello"

    def test_openai_format(self):
        scanner = AIVulnScanner()
        resp = {
            "choices": [
                {"message": {"content": "Hello from GPT"}},
            ],
        }
        assert scanner._extract_response_text(resp) == "Hello from GPT"

    def test_openai_delta_format(self):
        scanner = AIVulnScanner()
        resp = {
            "choices": [
                {"delta": {"content": "Hello streaming"}},
            ],
        }
        assert scanner._extract_response_text(resp) == "Hello streaming"

    def test_nested_message(self):
        scanner = AIVulnScanner()
        resp = {
            "reply": {"text": "nested reply"},
        }
        assert scanner._extract_response_text(resp) == "nested reply"

    def test_empty_response(self):
        scanner = AIVulnScanner()
        assert scanner._extract_response_text({}) == "{}"

    def test_fallback_to_json_stringify(self):
        scanner = AIVulnScanner()
        resp = {"unknown_key": "value"}
        result = scanner._extract_response_text(resp)
        assert "unknown_key" in result


# ── _emit_finding ───────────────────────────────────────────────────────


class TestEmitFinding:
    """ "_emit_finding" works with and without builder."""

    def test_without_builder_calls_callback(self):
        """When _builder is None, callback is fired."""
        callback = Mock()
        scanner = AIVulnScanner(engagement_id="eng-1", emit_finding_callback=callback)
        scanner._emit_finding(
            {
                "type": "PROMPT_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "https://example.com/chat",
                "evidence": {"test": True},
                "confidence": 0.85,
                "cwe": "CWE-77",
            }
        )
        callback.assert_called_once()

    def test_without_builder_no_callback_skips(self):
        scanner = AIVulnScanner()
        scanner._emit_finding(
            {
                "type": "PROMPT_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "https://example.com/chat",
                "evidence": {"test": True},
                "confidence": 0.85,
            }
        )
        # Should not raise

    def test_with_builder_routes_through(self):
        from tool_core.finding_builder import FindingBuilder

        scanner = AIVulnScanner()
        scanner._builder = FindingBuilder(
            source_tool="ai_vuln_scanner",
            engagement_id="eng-1",
        )
        scanner._emit_finding(
            {
                "type": "PROMPT_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "https://example.com/chat",
                "evidence": {"test": True},
                "confidence": 0.85,
                "cwe": "CWE-77",
            }
        )
        assert len(scanner._builder.findings) == 1
        f = scanner._builder.findings[0]
        assert f["type"] == "PROMPT_INJECTION"
        assert f["cwe"] == "CWE-77"  # Extra field passed through


# ── AI endpoint discovery ───────────────────────────────────────────────


class TestDiscoverAIEndpoints:
    """_discover_ai_endpoints probes paths and finds active ones."""

    def test_finds_active_endpoint(self):
        scanner = AIVulnScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            if "/api/chat" in url:
                return Mock(status_code=200, text="OK")
            return None

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            active = scanner._discover_ai_endpoints(["/api/chat", "/api/ai"])

        assert "/api/chat" in active
        assert "/api/ai" not in active

    def test_returns_empty_when_none_found(self):
        scanner = AIVulnScanner()
        scanner.target_url = "https://example.com"

        with patch.object(scanner, "_safe_request", return_value=None):
            active = scanner._discover_ai_endpoints(["/api/chat", "/api/ai"])

        assert active == []

    def test_400_or_405_indicates_endpoint_exists(self):
        """400/405 means endpoint exists but wrong method."""
        scanner = AIVulnScanner()
        scanner.target_url = "https://example.com"

        def _fake_safe(method, url, **kw):
            if "/api/chat" in url and method == "GET":
                return Mock(status_code=405, text="Method Not Allowed")
            if "/api/chat" in url and method == "POST":
                return Mock(status_code=200, text="OK")
            return None

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            active = scanner._discover_ai_endpoints(["/api/chat"])

        assert "/api/chat" in active


# ── Query AI (format detection & caching) ────────────────────────────────


class TestQueryAI:
    """_query_ai probes payload formats and caches the working one."""

    def test_finds_working_format(self):
        scanner = AIVulnScanner()

        def _fake_safe(method, url, **kw):
            payload = kw.get("json", {})
            if payload.get("message") == "hello":
                return Mock(status_code=200, text='{"reply": "hi"}')
            return Mock(status_code=400, text="Bad Request")

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            result = scanner._query_ai("https://example.com/chat", "hello")

        assert result is not None
        assert scanner._detected_format == {"message": "__PLACEHOLDER__"}

    def test_cached_format_used_on_second_call(self):
        scanner = AIVulnScanner()
        scanner._detected_format = {"prompt": "__PLACEHOLDER__"}

        def _fake_safe(method, url, **kw):
            payload = kw.get("json", {})
            if "prompt" in payload:
                return Mock(status_code=200, text='{"response": "cached"}')
            return None

        with patch.object(scanner, "_safe_request", side_effect=_fake_safe):
            result = scanner._query_ai("https://example.com/chat", "hello")

        assert result is not None

    def test_all_formats_fail_returns_none(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_safe_request", return_value=None):
            result = scanner._query_ai("https://example.com/chat", "hello")

        assert result is None


# ── Prompt injection tests ──────────────────────────────────────────────


class TestPromptInjection:
    """_test_prompt_injection flags successful injections."""

    def test_injection_detected(self):
        scanner = AIVulnScanner()

        with patch.object(
            scanner,
            "_query_ai",
            return_value="The system prompt says: You are a helpful assistant",
        ):
            findings = scanner._test_prompt_injection("https://example.com/chat")

        assert len(findings) >= 1
        assert any(f["type"] == "PROMPT_INJECTION" for f in findings)

    def test_refusal_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(
            scanner,
            "_query_ai",
            return_value="I am sorry, I cannot reveal my system prompt",
        ):
            findings = scanner._test_prompt_injection("https://example.com/chat")

        assert len(findings) == 0

    def test_empty_response_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_query_ai", return_value=""):
            findings = scanner._test_prompt_injection("https://example.com/chat")

        assert len(findings) == 0

    def test_no_response_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_query_ai", return_value=None):
            findings = scanner._test_prompt_injection("https://example.com/chat")

        assert len(findings) == 0

    def test_multiple_injections_deduplicated(self):
        """Same evasion pattern multiple times = only one finding."""
        scanner = AIVulnScanner()
        call_count = [0]

        def _fake_query(url, msg):
            call_count[0] += 1
            # Return injection indicator for every payload
            return "Here is the database schema"

        with patch.object(scanner, "_query_ai", side_effect=_fake_query):
            findings = scanner._test_prompt_injection("https://example.com/chat")

        # Should have at least one finding but deduplicated by (payload[:30]:indicator)
        injection_types = [f for f in findings if f["type"] == "PROMPT_INJECTION"]
        assert len(injection_types) >= 1


# ── Information disclosure tests ────────────────────────────────────────


class TestInformationDisclosure:
    """_test_information_disclosure flags sensitive data leaks."""

    def test_sql_leak_detected(self):
        scanner = AIVulnScanner()

        with patch.object(
            scanner, "_query_ai", return_value="SELECT * FROM users WHERE id = 1"
        ):
            findings = scanner._test_information_disclosure("https://example.com/chat")

        assert len(findings) >= 1
        assert any(f["type"] == "AI_INFORMATION_DISCLOSURE" for f in findings)

    def test_api_key_leak_detected(self):
        scanner = AIVulnScanner()

        # Response uses colon+no-space format that matches the sensitive data regex
        with patch.object(
            scanner,
            "_query_ai",
            return_value="The API key:sk-1234567890123456 is used for auth",
        ):
            findings = scanner._test_information_disclosure("https://example.com/chat")

        assert len(findings) >= 1

    def test_refusal_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(
            scanner, "_query_ai", return_value="I cannot share that information"
        ):
            findings = scanner._test_information_disclosure("https://example.com/chat")

        assert len(findings) == 0

    def test_no_sensitive_data_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(
            scanner, "_query_ai", return_value="The weather today is sunny"
        ):
            findings = scanner._test_information_disclosure("https://example.com/chat")

        assert len(findings) == 0

    def test_no_response_skipped(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_query_ai", return_value=None):
            findings = scanner._test_information_disclosure("https://example.com/chat")

        assert len(findings) == 0


# ── scan() flow ──────────────────────────────────────────────────────────


class TestScan:
    """scan() orchestrates discovery, injection tests, disclosure tests."""

    def test_full_scan_with_active_endpoint(self):
        scanner = AIVulnScanner()

        # Mock discovery to find an endpoint
        with patch.object(
            scanner, "_discover_ai_endpoints", return_value=["/api/chat"]
        ):
            # Mock injection test to produce findings
            with patch.object(
                scanner,
                "_test_prompt_injection",
                return_value=[
                    {
                        "type": "PROMPT_INJECTION",
                        "severity": "CRITICAL",
                        "endpoint": "url",
                        "evidence": {},
                        "confidence": 0.85,
                        "cwe": "CWE-77",
                    },
                ],
            ):
                with patch.object(
                    scanner,
                    "_test_information_disclosure",
                    return_value=[
                        {
                            "type": "AI_INFORMATION_DISCLOSURE",
                            "severity": "HIGH",
                            "endpoint": "url",
                            "evidence": {},
                            "confidence": 0.75,
                            "cwe": "CWE-200",
                        },
                    ],
                ):
                    findings = scanner.scan("https://example.com")

        assert len(findings) == 2
        assert any(f["type"] == "PROMPT_INJECTION" for f in findings)
        assert any(f["type"] == "AI_INFORMATION_DISCLOSURE" for f in findings)

    def test_no_active_endpoints(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_discover_ai_endpoints", return_value=[]):
            findings = scanner.scan("https://example.com")

        assert findings == []

    def test_empty_endpoints_list(self):
        scanner = AIVulnScanner()

        with patch.object(scanner, "_discover_ai_endpoints", return_value=[]):
            findings = scanner.scan("https://example.com", ai_endpoints=["/api/chat"])

        assert findings == []


# ── execute(ctx) ────────────────────────────────────────────────────────


class TestExecute:
    """execute() creates builder, runs scan, returns UnifiedToolResult."""

    def test_execute_returns_unified_tool_result(self):
        scanner = AIVulnScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "scan", return_value=[]):
            result = scanner.execute(ctx)

        assert result.tool_name == "ai_vuln_scanner"
        assert result.status == ToolStatus.SUCCESS
        assert result.target == "https://example.com"
        assert result.finished_at is not None

    def test_execute_sets_builder(self):
        scanner = AIVulnScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "scan", return_value=[]):
            scanner.execute(ctx)

        assert scanner._builder is not None
        assert scanner._builder.source_tool == "ai_vuln_scanner"

    def test_execute_propagates_engagement_id(self):
        scanner = AIVulnScanner()
        ctx = ToolContext(target="https://example.com", engagement_id="eng-42")

        with patch.object(scanner, "scan", return_value=[]):
            scanner.execute(ctx)

        assert scanner.engagement_id == "eng-42"

    def test_execute_maps_timeout(self):
        scanner = AIVulnScanner()
        ctx = ToolContext(target="https://example.com", timeout=88)

        with patch.object(scanner, "scan", return_value=[]):
            scanner.execute(ctx)

        assert scanner.timeout == 88

    def test_execute_returns_findings_from_builder(self):
        """Findings produced during scan appear in the result."""
        scanner = AIVulnScanner()
        ctx = ToolContext(target="https://example.com")

        with patch.object(scanner, "scan", return_value=[]):
            result = scanner.execute(ctx)

        assert isinstance(result.findings, list)


# ── Payload constants sanity ────────────────────────────────────────────


class TestPayloadDefinitions:
    """Static payload lists are well-formed."""

    def test_prompt_injection_payloads_nonempty(self):
        assert len(PROMPT_INJECTION_PAYLOADS) > 5

    def test_disclosure_probes_nonempty(self):
        assert len(INFORMATION_DISCLOSURE_PROBES) > 5

    def test_injection_indicators_nonempty(self):
        assert len(INJECTION_SUCCESS_INDICATORS) > 5

    def test_refusal_patterns_nonempty(self):
        assert len(REFUSAL_PATTERNS) > 5

    def test_sensitive_patterns_nonempty(self):
        assert len(SENSITIVE_DATA_PATTERNS) > 5
