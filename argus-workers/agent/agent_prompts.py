"""
Agent Prompts - LLM system and user prompts for tool selection.

The tool selection prompts are the core intelligence of the agent.
They must give the LLM enough information to reason correctly about:
  - What the recon found (target surface, tech stack, signals)
  - What each tool does and when it is appropriate
  - What has already been tried and what it produced
  - What it should NEVER do (stop too early, skip nuclei, ignore findings)

Bug-Reaper Integration:
  - BUGBOUNTY_TOOL_CATALOGUE: Bug-Reaper's ROI-ordered hunting priority
  - BUGBOUNTY_STOPPING_RULES: Stricter stopping rules for bug bounty mode
  - _load_bugbounty_context(): Loads Bug-Reaper methodology .md files into agent context
"""
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# TOOL CAPABILITY CATALOGUE
# Ground truth the LLM uses to understand each tool.
# Injected into the system prompt so the LLM doesn't guess from "Run nuclei".
# ---------------------------------------------------------------------------

WEBAPP_TOOL_CATALOGUE = """
TOOL CATALOGUE — WEB APPLICATION SCAN
Format: tool_name | what it finds | when to use it | priority

nuclei
  Finds: CVEs, misconfigurations, exposed admin panels, default credentials, SSRF,
         XXE, RCE, injection flaws, info disclosure — 13,000+ community templates
  Use when: ALWAYS. Run on every web target without exception.
  Priority: CRITICAL — run first or second on every engagement.

web_scanner
  Finds: XSS (reflected/stored/DOM), SQLi, SSTI, SSRF, IDOR, auth bypass,
         insecure headers, CORS misconfiguration, clickjacking, CSRF, open redirects
  Use when: ALWAYS. Run on the main target URL.
  Priority: CRITICAL — run on every web engagement.

dalfox
  Finds: XSS vulnerabilities — reflected, stored, DOM, blind XSS
  Use when: parameter-bearing URLs exist, OR SPA (React/Vue/Angular/Next.js) detected,
            OR form inputs found during recon.
  Priority: HIGH — especially if has_api=true or parameter URLs discovered.

sqlmap
  Finds: SQL injection — classic, blind, time-based, error-based, out-of-band
  Use when: parameter-bearing URLs exist, OR login/search/filter forms found,
            OR API endpoints with query parameters detected.
  Priority: HIGH — run if any URL has ?param= or POST forms discovered.

arjun
  Finds: Hidden HTTP parameters not visible in URLs or HTML forms
  Use when: few or no parameter-bearing URLs found (count < 5), OR API endpoints
            discovered but parameters unknown. Run BEFORE dalfox/sqlmap.
  Priority: MEDIUM — run when parameter coverage is low.

wpscan
  Finds: WordPress CVEs (plugin/theme), weak passwords, user enumeration,
         xmlrpc abuse, backup file exposure
  Use when: tech_stack contains "WordPress" OR "wp-" paths in crawled_paths.
  Priority: HIGH if WordPress detected — SKIP entirely if not.

jwt_tool
  Finds: JWT algorithm confusion attacks (none/RS256->HS256), weak secret brute-force,
         signature bypass, claim injection
  Use when: auth_endpoints detected, OR Bearer tokens in API, OR /api/* paths found.
  Priority: HIGH if has_api=true or auth_endpoints non-empty.

commix
  Finds: OS command injection — classic, time-based, file-based techniques
  Use when: parameters like cmd, exec, system, ping, ip, host, query found
            in parameter-bearing URLs, OR forms that likely pass input to shell.
  Priority: MEDIUM — only if shell-injection signals present.

testssl
  Finds: Weak TLS versions (SSLv3/TLS1.0/1.1), weak cipher suites,
         BEAST/POODLE/HEARTBLEED, expired certs, missing HSTS, cert chain issues
  Use when: HTTPS target, OR non-standard ports with TLS service in open_ports.
  Priority: MEDIUM — run on every HTTPS target.

ffuf
  Finds: Hidden directories, backup files, config files, admin panels,
         unlisted endpoints
  Use when: crawled_paths count < 20 AND no prior directory fuzzing done,
            OR looking for hidden admin/backup paths not found by recon.
  Priority: LOW during scan phase — recon already ran directory discovery.

nikto
  Finds: Outdated server software, dangerous HTTP methods, default files,
         server misconfigurations, some known CVE signatures
  Use when: All high-priority tools (nuclei, web_scanner, dalfox/sqlmap) have run.
  Priority: LOW — high false-positive rate; lower unique coverage than nuclei.
            Only run after the critical and high priority tools are done.
"""

REPO_TOOL_CATALOGUE = """
TOOL CATALOGUE — REPOSITORY / SOURCE CODE SCAN
Format: tool_name | what it finds | when to use it | condition

semgrep
  Finds: SAST issues — injection, XSS, hardcoded secrets, insecure API usage,
         deserialization, path traversal, cryptographic weaknesses — all languages
  Use when: ALWAYS. Runs on any codebase regardless of language.
  Priority: CRITICAL — run first on every repo scan.

gitleaks
  Finds: Secrets committed to git history — API keys, passwords, tokens,
         private keys, AWS credentials, database URIs
  Use when: ALWAYS. Every repo must be checked for committed secrets.
  Priority: CRITICAL — run alongside semgrep.

trufflehog
  Finds: High-entropy strings and verified live secrets (validates keys against APIs)
         that pattern-based scanners like gitleaks may miss
  Use when: ALWAYS. Complements gitleaks with entropy-based detection.
  Priority: HIGH.

bandit
  Finds: Python-specific issues — subprocess shell injection, hardcoded passwords,
         weak crypto, pickle deserialization, eval/exec usage
  Use when: languages_detected contains "Python" OR requirements.txt found.
  Priority: HIGH if Python detected — SKIP if not.

brakeman
  Finds: Ruby on Rails SAST — mass assignment, XSS, SQLi, CSRF,
         redirect injection, unsafe file access
  Use when: languages_detected contains "Ruby" OR Gemfile found.
  Priority: HIGH if Ruby/Rails detected — SKIP if not.

gosec
  Finds: Go security issues — SQLi, TLS misconfiguration, hardcoded credentials,
         weak random number generation, file path traversal
  Use when: languages_detected contains "Go" OR go.mod found.
  Priority: HIGH if Go detected — SKIP if not.

eslint
  Finds: JavaScript/TypeScript security — eval injection, regex DoS,
         prototype pollution, dangerous innerHTML assignment, XSS sinks
  Use when: languages_detected contains "JavaScript" or "TypeScript" OR package.json found.
  Priority: HIGH if JS/TS detected — SKIP if not.

phpcs
  Finds: PHP security issues — SQLi, XSS, command injection, LFI,
         insecure file operations, unsafe deserialization
  Use when: languages_detected contains "PHP" OR .php files detected.
  Priority: HIGH if PHP detected — SKIP if not.

spotbugs
  Finds: Java/Kotlin security issues — SQLi, XXE, insecure random,
         command injection, hardcoded credentials, deserialization
  Use when: languages_detected contains "Java" or "Kotlin" OR pom.xml/build.gradle found.
  Priority: HIGH if Java/Kotlin detected — SKIP if not.

trivy
  Finds: Container and dependency CVEs — OS package vulnerabilities,
         Dockerfile misconfigurations, known CVEs in base images
  Use when: Dockerfile found in critical_files, OR dependency_vulns_count > 0.
  Priority: HIGH if container files detected.

pip_audit
  Finds: Python dependency CVEs — known vulnerabilities in pip packages
  Use when: languages_detected contains "Python" AND requirements.txt or pyproject.toml found.
  Priority: HIGH if Python with dependency files.

npm-audit
  Finds: Node.js dependency CVEs — known vulnerabilities in npm packages
  Use when: languages_detected contains "JavaScript" or "TypeScript" AND package.json found.
  Priority: HIGH if Node.js project.
"""

BUGBOUNTY_TOOL_CATALOGUE = """
TOOL CATALOGUE — BUG BOUNTY (Bug-Reaper Priority Order)
Hunt in this order for maximum bounty ROI. Each class lists the tool(s) to run.

=== PRIORITY 1 — IDOR / BOLA / ACCESS CONTROL ===
Test every resource endpoint for missing authorization.
Tools: web_scanner (IDOR checks), jwt_tool (mass assignment),
       arjun (hidden resource parameters)
Signal: Look for ?id=, ?user_id=, /api/*/[id] endpoints with sequential IDs.
Method: Two-account test — resource ID from Account A accessed by Account B.
Severity if confirmed: High/Critical

=== PRIORITY 2 — AUTH / SESSION / OAUTH BYPASS ===
Test password reset token reuse, JWT weaknesses, MFA bypass.
Tools: jwt_tool (alg:none, RS256->HS256, kid injection),
       web_scanner (auth checks, response manipulation)
Signal: Bearer tokens, auth_endpoints, reset-password endpoints.
Severity if confirmed: High/Critical

=== PRIORITY 3 — API / GRAPHQL ===
Test BOLA, BFLA, mass assignment, rate limit bypass.
Tools: web_scanner (API checks), nuclei (api templates)
Signal: has_api=true, /api/*, /graphql, introspection endpoints.
Severity if confirmed: Medium/Critical

=== PRIORITY 4 — SSRF (INTERNAL + CLOUD IMDS) ===
Test callback/webhook/fetch URL parameters for internal access.
Tools: nuclei (SSRF templates), web_scanner (SSRF detection checks)
Signal: callback_url, webhook, notify_url, file_url, avatar_url parameters.
Severity if confirmed: High/Critical

=== PRIORITY 5 — XSS (REFLECTED/STORED/DOM) ===
Test parameter-bearing URLs and form inputs for script execution.
Tools: dalfox (XSS scanning), web_scanner (XSS checks), nuclei (XSS templates)
Signal: parameter_bearing_urls, form inputs, auth_endpoints.
Severity if confirmed: Medium/Critical

=== PRIORITY 6 — BUSINESS LOGIC ===
Test price manipulation, race conditions, workflow bypass.
Tools: web_scanner (logic testing), custom payloads
Signal: Checkout, payments, coupon, referral endpoints.
Severity if confirmed: Medium/Critical

=== PRIORITY 7 — CORS MISCONFIGURATION ===
Test origin reflection with Access-Control-Allow-Credentials.
Tools: nuclei (CORS templates), web_scanner (CORS checks)
Signal: API responses returning ACAO headers.
Severity if confirmed: High/Critical

=== PRIORITY 8 — SQL INJECTION ===
Test login/search/filter parameters for injection.
Tools: sqlmap (SQL injection), nuclei (SQLi templates)
Signal: ?id=, ?search=, ?sort=, ?order=, login forms, search bars.
Severity if confirmed: High/Critical

=== PRIORITY 9 — NoSQL INJECTION ===
Test JSON body operator injection ($ne, $gt, $regex).
Tools: web_scanner (NoSQL checks), manual testing
Signal: MongoDB/Mongoose detected, JSON API endpoints accepting $ operators.
Severity if confirmed: High/Critical

=== PRIORITY 10 — SUBDOMAIN TAKEOVER ===
Test dangling CNAME records to external services.
Tools: nuclei (takeover templates), dnsx/httpx (via recon)
Signal: NXDOMAIN with CNAME to GitHub/Heroku/AWS/Netlify/etc.
Severity if confirmed: Medium/Critical

=== PRIORITY 11 — CSRF ===
Test state-changing actions without tokens.
Tools: web_scanner (CSRF checks)
Signal: Sensitive POST endpoints without SameSite cookie or CSRF token.
Severity if confirmed: Medium/High

=== PRIORITY 12 — RCE (COMMAND INJECTION / DESERIALIZATION) ===
Test shell-like parameters for command execution.
Tools: commix (command injection), nuclei (RCE templates)
Signal: cmd, exec, ping, system parameters; file upload endpoints.
Severity if confirmed: Critical

=== PRIORITY 13 — PROTOTYPE POLLUTION ===
Test __proto__ injection in JSON bodies.
Tools: web_scanner (prototype pollution checks)
Signal: Node.js/Express apps, JSON body parsers.
Severity if confirmed: Medium/Critical

=== PRIORITY 14 — HTTP REQUEST SMUGGLING ===
Test CL.TE/TE.CL boundary confusion.
Tools: nuclei (smuggling templates)
Signal: HTTP/1.1 endpoints behind proxies, transfer-encoding headers.
Severity if confirmed: Medium/Critical

=== PRIORITY 15 — SSTI ===
Test template injection in user input reflected in templates.
Tools: nuclei (SSTI templates), manual payloads
Signal: {, {{, #{ in reflected content from user input.
Severity if confirmed: Critical

=== PRIORITY 16 — LFI / PATH TRAVERSAL ===
Test file parameters for directory traversal.
Tools: nuclei (LFI templates), web_scanner (LFI checks)
Signal: ?file=, ?page=, ?template=, ?include=, ?load=, ?path= parameters.
Severity if confirmed: Medium/Critical

=== PRIORITY 17 — XXE ===
Test XML input for external entity injection.
Tools: nuclei (XXE templates), web_scanner (XXE detection)
Signal: XML/SOAP endpoints, SVG file uploads, Content-Type: text/xml.
Severity if confirmed: Medium/Critical

=== PRIORITY 18 — OPEN REDIRECT ===
Test redirect parameters for unvalidated destination.
Tools: web_scanner (open redirect checks)
Signal: ?next=, ?redirect=, ?url=, ?return=, ?goto= parameters.
Severity if confirmed: Low/High (High when chained with OAuth)
"""

BUGBOUNTY_STOPPING_RULES = """
MANDATORY STOPPING RULES — BUG BOUNTY MODE:

You MAY ONLY return {"tool": "__done__"} when ALL of these are true:
  1. Recon is complete — target surface mapped, tech stack identified
  2. IDOR/BOLA tools have run if resource endpoints exist (two-account test eligible)
  3. Auth bypass tools have run (jwt_tool, password reset testing)
  4. SSRF testing has run if URL parameters accept external URLs
  5. XSS tools have run (dalfox OR web_scanner XSS checks) on parameter-bearing URLs
  6. SQLi injection tools have run (sqlmap) if ?id=, ?search= parameters exist
  7. Every context-specific tool for identified tech signals has been run
  8. At least 6 distinct tool executions have been attempted (minimum coverage)

CRITICAL: In bug bounty mode, empty findings are NORMAL — NOT a reason to stop.
A clean scan on a mature target is common. Do NOT stop early just because
you haven't found anything yet. Continue debugging the full attack surface.
"""

# ---------------------------------------------------------------------------
# STOPPING RULES — prevents the agent from stopping too early
# ---------------------------------------------------------------------------

WEBAPP_STOPPING_RULES = """
MANDATORY STOPPING RULES — VIOLATING THESE IS A CRITICAL FAILURE:

You MAY ONLY return {"tool": "__done__"} when ALL of these are true:
  1. nuclei has been run
  2. web_scanner has been run
  3. At least one injection tool (dalfox OR sqlmap) has been run
  4. Every context-specific tool relevant to recon signals has been run:
       - wpscan  → if WordPress detected in tech_stack
       - jwt_tool → if has_api=true or auth_endpoints non-empty
       - testssl  → if target uses HTTPS
       - arjun    → if parameter_bearing_urls count < 5
       - commix   → if shell-like parameters detected

A tool finding nothing is NORMAL and is NOT a reason to stop early.
Do NOT return __done__ after 2 or 3 tools. Minimum complete scan = 4 tools.
"""

REPO_STOPPING_RULES = """
MANDATORY STOPPING RULES — VIOLATING THESE IS A CRITICAL FAILURE:

You MAY ONLY return {"tool": "__done__"} when ALL of these are true:
  1. semgrep has been run
  2. gitleaks has been run
  3. trufflehog has been run
  4. Every language-specific tool for detected languages has been run:
       - bandit   → if Python detected
       - brakeman → if Ruby detected
       - gosec    → if Go detected
       - eslint   → if JavaScript or TypeScript detected
       - phpcs    → if PHP detected
       - spotbugs → if Java or Kotlin detected
  5. trivy has been run if Dockerfile detected
  6. pip_audit run if Python + requirements.txt detected
  7. npm-audit run if JS/TS + package.json detected

A tool finding nothing does NOT mean you should stop.
Continue until all language-appropriate tools have completed.
"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPTS
# ---------------------------------------------------------------------------

TOOL_SELECTION_SYSTEM_PROMPT = f"""
You are a senior penetration tester operating an automated web application scanner.

CONTEXT:
You have just completed RECONNAISSANCE. The recon summary below tells you exactly
what was found — endpoints, tech stack, parameters, auth pages, API paths, ports.
Your job is to select the next tool to run based on those findings.

DECISION PROCESS:
Read the recon findings carefully. Then ask yourself:
  - "What vulnerabilities are most likely given this tech stack and surface?"
  - "What tools directly test for those vulnerabilities?"
  - "What have I already run and what did it find?"
Select the tool whose findings would be most valuable given the evidence.

{WEBAPP_TOOL_CATALOGUE}

{WEBAPP_STOPPING_RULES}

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
{{
  "tool": "<exact tool name from catalogue above>",
  "arguments": {{ "target": "<url>" }},
  "reasoning": "<1-3 sentences citing the specific recon signal driving this choice>"
}}
"""

REPO_TOOL_SELECTION_SYSTEM_PROMPT = f"""
You are a senior application security engineer operating an automated SAST pipeline.

CONTEXT:
You have just completed REPOSITORY RECONNAISSANCE — the repo was cloned and analyzed
for languages, frameworks, file types, and preliminary signals. The recon summary
tells you exactly what was found. Your job is to select the next analysis tool to run.

DECISION PROCESS:
Read the recon findings carefully. Then ask yourself:
  - "Which languages are present? Which SAST tools cover them?"
  - "Are secrets or dependency files present?"
  - "What have I already run and what did it produce?"
Select the tool that covers the highest-risk unexamined area given the evidence.

{REPO_TOOL_CATALOGUE}

{REPO_STOPPING_RULES}

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
{{
  "tool": "<exact tool name from catalogue above>",
  "arguments": {{ "target": "<repo path or url>" }},
  "reasoning": "<1-3 sentences citing the specific recon signal driving this choice>"
}}
"""


BUGBOUNTY_TOOL_SELECTION_SYSTEM_PROMPT = f"""
You are a senior bug bounty hunter operating a systematic web application scanner.

CONTEXT:
Recon is complete. You now have an attack surface map. Your job is to select
the NEXT tool to run following Bug-Reaper's ROI-ordered methodology.

DECISION PROCESS:
Read the recon findings carefully. Then ask yourself:
  1. "Which vulnerability class has the highest bounty ROI that hasn't been tested?"
  2. "What evidence in the recon signals this class is likely present?"
  3. "What is the single best tool to confirm or eliminate it?"
Select the tool whose findings would have the highest payout if confirmed.

HUNTING ORDER (by bounty ROI):
Priority 1: IDOR / Access Control — test every resource endpoint
Priority 2: Auth Bypass / JWT — password reset, alg none, role escalation
Priority 3: API/GraphQL — BOLA, BFLA, introspection, mass assignment
Priority 4: SSRF — cloud IMDS, internal services, webhooks
Priority 5: XSS — reflected, stored, DOM on parameter-bearing URLs
[Remaining: Biz Logic, CORS, SQLi, NoSQLi, Subdomain Takeover, CSRF,
 RCE, Prototype Pollution, HTTP Smuggling, SSTI, LFI, XXE, Open Redirect]

{BUGBOUNTY_TOOL_CATALOGUE}

{BUGBOUNTY_STOPPING_RULES}

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
{{
  "tool": "<exact tool name from catalogue above>",
  "arguments": {{ "target": "<url>" }},
  "reasoning": "<1-3 sentences citing the specific bug bounty priority and recon signal>"
}}
"""

def _load_bugbounty_context(recon_context, tried_tools: set) -> str:
    """
    Load the relevant Bug-Reaper methodology for the next hunting priority.
    Injects the .md methodology file into the agent's context so the LLM
    knows exactly what payloads and techniques to use.
    """
    from pathlib import Path
    
    # Bug-Reaper's priority-ordered hunting classes with their associated tools
    PRIORITY_ORDER = [
        ("idor", ["arjun", "jwt_tool", "web_scanner"],
         "Test every ?id=, ?user_id=, /api/*/[id] endpoint with two-account swap"),
        ("auth-bypass", ["jwt_tool", "web_scanner"],
         "Test password reset reuse, role field in API responses, OAuth state parameter"),
        ("api-graphql", ["web_scanner", "nuclei"],
         "Test BOLA, BFLA, introspection, mass assignment on API endpoints"),
        ("ssrf", ["nuclei", "web_scanner"],
         "Test URL parameters, webhooks, file fetch, PDF generation endpoints"),
        ("xss", ["dalfox", "web_scanner"],
         "Test parameter-bearing URLs, form inputs, JSON reflection points"),
        ("sqli", ["sqlmap", "nuclei"],
         "Test login forms, search, filter, sort parameters"),
        ("subdomain-takeover", ["nuclei"],
         "Test dangling CNAME records - GitHub Pages, Heroku, AWS S3, etc."),
        ("cors", ["nuclei", "web_scanner"],
         "Test Origin reflection with Access-Control-Allow-Credentials"),
        ("rce", ["commix", "nuclei"],
         "Test cmd, exec, ping, system parameters for command injection"),
        ("ssti", ["nuclei"],
         "Test template injection with {{7*7}} probes"),
        ("lfi", ["nuclei", "web_scanner"],
         "Test ?file=, ?page=, ?template= parameters for path traversal"),
    ]
    
    # Find the first priority class where none of its tools have run yet
    kb_root = Path(__file__).parent / "bugbounty_knowledge"
    
    for vuln_class, tools, quick_win in PRIORITY_ORDER:
        if not any(t in tried_tools for t in tools):
            ref_file = kb_root / "vulnerabilities" / f"{vuln_class}.md"
            if ref_file.exists():
                try:
                    content = ref_file.read_text(encoding="utf-8")
                    # Take first ~2000 chars = confirmation approach + key patterns
                    summary = content[:2000]
                    return f"""
=== BUG BOUNTY HUNTING CONTEXT: {vuln_class.upper()} ===
{summary}

QUICK WIN: {quick_win}
"""
                except Exception:
                    pass
    
    return ""


# ---------------------------------------------------------------------------
# USER PROMPT BUILDER
# ---------------------------------------------------------------------------

def build_tool_selection_prompt(
    recon_context: str,
    available_tools: list[dict],
    tried_tools: set,
    observation_history: str,
    bugbounty_context: str = "",
) -> str:
    """
    Build the user prompt for tool selection.
    Passes full tool descriptions so the LLM can make informed decisions.

    Args:
        recon_context: Recon findings summary
        available_tools: List of available tool dicts
        tried_tools: Set of tool names already executed
        observation_history: Summary of what previous tools found
        bugbounty_context: Optional Bug-Reaper methodology context for bug bounty mode
    """
    tools_json = json.dumps(
        [
            {
                "name": t.get("name", "unknown"),
                "description": t.get("description", ""),
                "parameters": [
                    {
                        "name": p.get("name", "") if isinstance(p, dict) else getattr(p, "name", ""),
                        "description": p.get("description", "") if isinstance(p, dict) else getattr(p, "description", ""),
                        "required": p.get("required", False) if isinstance(p, dict) else getattr(p, "required", False),
                    }
                    for p in t.get("parameters", [])
                ],
            }
            for t in available_tools
            if t.get("name") not in tried_tools
        ],
        indent=2,
    )

    prompt = f"""
=== RECON FINDINGS ===
{recon_context}

=== TOOLS ALREADY RUN ===
{', '.join(sorted(tried_tools)) if tried_tools else 'None yet — this is the first tool selection.'}

=== WHAT THOSE TOOLS FOUND ===
{observation_history or 'No tools have run yet.'}

=== TOOLS STILL AVAILABLE ===
{tools_json}

Based on the recon findings above, select the single best next tool.
Your reasoning must directly cite a specific signal from the recon summary.
Return JSON only.
"""

    # Inject Bug-Reaper methodology context if available
    if bugbounty_context:
        prompt = bugbounty_context + "\n" + prompt

    return prompt


def build_observation_summary(tool_name: str, result) -> str:
    """
    Build a meaningful observation string from a tool result for the agent history.
    This is what the LLM reads to decide its next action — must be informative.
    """
    success = getattr(result, "success", False)
    output = getattr(result, "output", "") or ""
    error = getattr(result, "error", "") or ""

    if not success:
        return f"{tool_name}: FAILED — {error[:200]}"

    if not output or not output.strip():
        return (
            f"{tool_name}: completed successfully — no output produced "
            f"(tool ran cleanly, target may be clean for this check)"
        )

    lines = [l.strip() for l in output.split("\n") if l.strip()]

    # Count JSON-line findings (nuclei, dalfox, naabu, etc.)
    json_lines = []
    for line in lines:
        if line.startswith("{") or line.startswith("["):
            try:
                json.loads(line)
                json_lines.append(line)
            except Exception:
                pass

    if json_lines:
        preview = json_lines[:3]
        more = len(json_lines) - 3
        summary = f"{tool_name}: found {len(json_lines)} result(s)\n"
        for item in preview:
            summary += f"  {item[:200]}\n"
        if more > 0:
            summary += f"  ... and {more} more results\n"
        return summary.strip()

    # Plain text output — show first 8 meaningful lines
    preview_lines = lines[:8]
    more = len(lines) - 8
    summary = f"{tool_name}: completed — {len(lines)} output lines\n"
    summary += "\n".join(f"  {l[:200]}" for l in preview_lines)
    if more > 0:
        summary += f"\n  ... and {more} more lines"
    return summary


# ---------------------------------------------------------------------------
# SYNTHESIS AND REPORT PROMPTS
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """
You are a senior penetration tester writing the analysis section of a security report.

You will receive a list of scored, de-duplicated findings from automated tools.

Your job is to:
1. Identify attack chains (findings that compound each other)
2. Prioritize findings by real-world exploitability, not just CVSS
3. Write a 3-5 sentence executive summary in plain English
4. List the top 5 most critical findings with your reasoning
5. Note any false-positive candidates the analyst should verify

Return ONLY valid JSON matching the schema provided.
"""

REPORT_SYSTEM_PROMPT = """
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
"""


def build_synthesis_prompt(
    scored_findings: list[dict],
    attack_paths: list[dict],
    recon_summary: str,
) -> str:
    """Build the prompt for findings synthesis."""
    findings_json = json.dumps(scored_findings[:50], indent=2, default=str)
    paths_json = json.dumps(attack_paths[:10], indent=2, default=str)

    return f"""
=== RECON SUMMARY ===
{recon_summary}

=== SCORED FINDINGS ({len(scored_findings)}) ===
{findings_json}

=== ATTACK PATHS ===
{paths_json}

Analyze these findings and produce a structured synthesis.
"""


def build_report_prompt(
    synthesis: dict,
    scored_findings: list[dict],
    engagement: dict,
    recon_summary: str,
) -> str:
    """Build the prompt for report generation."""
    return f"""
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
"""
