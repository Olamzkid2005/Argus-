"""
Agent Prompts - LLM system and user prompts for tool selection.
"""
import json

TOOL_SELECTION_SYSTEM_PROMPT = '''
You are an expert penetration tester deciding which security tool to run next.

You have already completed reconnaissance. Your job is to select ONE tool from
the provided list that will yield the highest-value findings given what was discovered.

Rules:
- Return ONLY valid JSON. No markdown. No explanation outside the JSON.
- Select tools in logical order: parameter discovery before injection testing.
- Do NOT re-run a tool already in tried_tools.
- If you believe no further tools are needed, set 'tool' to '__done__'.
- Set 'arguments' to match the tool's parameter schema exactly.
- Put your reasoning in the 'reasoning' field (max 100 words).

Response format (JSON only):
{
  "tool": "<tool_name>",
  "arguments": { "target": "<url>", ... },
  "reasoning": "<why this tool, why these args>"
}
'''


SYNTHESIS_SYSTEM_PROMPT = '''
You are a senior penetration tester writing the analysis section of a security report.

You will receive a list of scored, de-duplicated findings from automated tools.

Your job is to:
1. Identify attack chains (findings that compound each other)
2. Prioritize findings by real-world exploitability, not just CVSS
3. Write a 3-5 sentence executive summary in plain English
4. List the top 5 most critical findings with your reasoning
5. Note any false-positive candidates the analyst should verify

Return ONLY valid JSON matching the schema provided.
'''


REPORT_SYSTEM_PROMPT = '''
You are writing a professional penetration test report for a technical audience.

Structure your report with these sections:
1. Executive Summary (non-technical, 2-3 paragraphs)
2. Scope and Methodology
3. Findings Summary Table (severity, finding name, affected endpoint)
4. Detailed Findings (one entry per finding: description, evidence, impact, remediation)
5. Remediation Roadmap (prioritized action items by severity)
6. Conclusion

Return as structured JSON matching the schema provided.
Use professional security report language. Be specific about evidence.
'''


def build_tool_selection_prompt(
    recon_context: str,
    available_tools: list[dict],
    tried_tools: set,
    observation_history: str,
) -> str:
    """Build the user prompt for tool selection."""
    tools_json = json.dumps(
        [
            {
                "name": t.get("name", "unknown"),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", []),
            }
            for t in available_tools
            if t.get("name") not in tried_tools
        ],
        indent=2,
    )

    return f'''
=== RECON SUMMARY ===
{recon_context}

=== ALREADY RAN ===
{', '.join(sorted(tried_tools)) or 'none'}

=== OBSERVATIONS SO FAR ===
{observation_history or 'No observations yet.'}

=== AVAILABLE TOOLS ===
{tools_json}

Select the single best tool to run next. Return JSON only.
'''


def build_synthesis_prompt(
    scored_findings: list[dict],
    attack_paths: list[dict],
    recon_summary: str,
) -> str:
    """Build the prompt for findings synthesis."""
    findings_json = json.dumps(scored_findings[:50], indent=2, default=str)
    paths_json = json.dumps(attack_paths[:10], indent=2, default=str)

    return f'''
=== RECON SUMMARY ===
{recon_summary}

=== SCORED FINDINGS ({len(scored_findings)}) ===
{findings_json}

=== ATTACK PATHS ===
{paths_json}

Analyze these findings and produce a structured synthesis.
'''


def build_report_prompt(
    synthesis: dict,
    scored_findings: list[dict],
    engagement: dict,
    recon_summary: str,
) -> str:
    """Build the prompt for report generation."""
    return f'''
=== ENGAGEMENT ===
Target: {engagement.get("target_url", "N/A")}
Type: {engagement.get("scan_type", "N/A")}

=== RECON SUMMARY ===
{recon_summary}

=== SYNTHESIS ===
{json.dumps(synthesis, indent=2, default=str)}

=== FINDINGS ({len(scored_findings)}) ===
{json.dumps(scored_findings[:100], indent=2, default=str)}

Generate a professional penetration test report.
'''
