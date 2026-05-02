"""Tests for LLM tool selection prompts."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_prompts import (
    TOOL_SELECTION_SYSTEM_PROMPT,
    build_report_prompt,
    build_synthesis_prompt,
    build_tool_selection_prompt,
)
from models.recon_context import ReconContext


class TestAgentPrompts:
    def test_system_prompt_contains_json_instruction(self):
        """System prompt should instruct JSON-only response."""
        assert "JSON" in TOOL_SELECTION_SYSTEM_PROMPT
        assert "__done__" in TOOL_SELECTION_SYSTEM_PROMPT

    def test_prompt_excludes_tried_tools(self):
        """tried_tools set removes tools from the available list."""
        tools = [
            {"name": "nuclei", "description": "Vuln scanner", "parameters": []},
            {"name": "dalfox", "description": "XSS scanner", "parameters": []},
            {"name": "sqlmap", "description": "SQLi scanner", "parameters": []},
        ]
        prompt = build_tool_selection_prompt(
            recon_context="test",
            available_tools=tools,
            tried_tools={"dalfox"},
            observation_history="",
        )
        assert "nuclei" in prompt
        assert "sqlmap" in prompt
        # dalfox should not appear in the AVAILABLE TOOLS section
        avail_section = prompt.split("=== AVAILABLE TOOLS ===")[-1] if "=== AVAILABLE TOOLS ===" in prompt else prompt
        assert "dalfox" not in avail_section

    def test_prompt_under_4k_tokens(self):
        """Combined prompt should stay under 4096 tokens (~16k chars)."""
        tools = [
            {"name": f"tool_{i}", "description": "test " * 10, "parameters": []}
            for i in range(20)
        ]
        ctx = ReconContext(
            target_url="https://example.com",
            live_endpoints=[f"https://example.com/{i}" for i in range(50)],
            subdomains=[f"sub{i}.example.com" for i in range(20)],
            findings_count=500,
        )
        prompt = build_tool_selection_prompt(
            recon_context=ctx.to_llm_summary(),
            available_tools=tools,
            tried_tools=set(),
            observation_history="",
        )
        full = TOOL_SELECTION_SYSTEM_PROMPT + "\n" + prompt
        assert len(full) < 16000, f"Prompt too long: {len(full)} chars"

    def test_prompt_format_valid_json(self):
        """Prompt should instruct JSON-only response correctly."""
        assert "Return ONLY valid JSON" in TOOL_SELECTION_SYSTEM_PROMPT
        assert "tool" in TOOL_SELECTION_SYSTEM_PROMPT
        assert "reasoning" in TOOL_SELECTION_SYSTEM_PROMPT

    def test_build_synthesis_prompt(self):
        """Synthesis prompt should include findings and recon summary."""
        prompt = build_synthesis_prompt(
            scored_findings=[{"type": "SQLI", "severity": "HIGH"}],
            attack_paths=[{"description": "Test attack chain"}],
            recon_summary="Target: example.com",
        )
        assert "SQLI" in prompt
        assert "example.com" in prompt

    def test_build_report_prompt(self):
        """Report prompt should include engagement info and findings."""
        prompt = build_report_prompt(
            synthesis={"executive_summary": "Test"},
            scored_findings=[{"type": "XSS", "severity": "MEDIUM"}],
            engagement={"target_url": "https://example.com"},
            recon_summary="Target: example.com",
        )
        assert "example.com" in prompt
        assert "XSS" in prompt
