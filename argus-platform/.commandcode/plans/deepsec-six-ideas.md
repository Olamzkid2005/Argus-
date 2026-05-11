# DeepSec → Argus Integration Plan

## Summary

Six surgical improvements mapped directly onto existing Argus code. Build in sequence — each is independent and testable alone.

## Build Order

1. **test\_patterns** — 30m, zero risk, prevents future regressions
2. **signal\_quality / noise tier** — 30m, pure labelling, changes nothing at runtime yet
3. **requires gate** — 1h, stops wpscan running on non-WordPress targets
4. **tech-aware prompt** — 2h, immediately improves agent tool selection on known-stack targets
5. **target context paragraph** — 1h, makes the "WHAT WE KNOW" section genuinely informative
6. **CandidateList contract** — half day, structural cleanup that makes everything downstream cleaner

---

## Idea 1: Noise Tier on ToolDefinition

### File: `argus-workers/tool_definitions.py`

Add `SignalQuality` enum and field to `ToolDefinition`:

```python
from enum import Enum

class SignalQuality(str, Enum):
    CONFIRMED  = "confirmed"   # nuclei CVE hit — nearly always real
    PROBABLE   = "probable"    # dalfox/sqlmap — tool confirmed the vuln
    CANDIDATE  = "candidate"   # nikto, ffuf, naabu — needs investigation

@dataclass
class ToolDefinition:
    name: str
    description: str
    phases: list[PhaseName]
    signal_quality: SignalQuality = SignalQuality.CANDIDATE  # safe default
    # ... existing fields unchanged
```

Tag each tool when registering:

```python
_register(ToolDefinition("nuclei",    "...", phases=["scan"], signal_quality=SignalQuality.CONFIRMED))
_register(ToolDefinition("dalfox",    "...", phases=["scan"], signal_quality=SignalQuality.PROBABLE))
_register(ToolDefinition("sqlmap",    "...", phases=["scan"], signal_quality=SignalQuality.PROBABLE))
_register(ToolDefinition("web_scanner","...",phases=["scan"], signal_quality=SignalQuality.PROBABLE))
_register(ToolDefinition("arjun",     "...", phases=["scan"], signal_quality=SignalQuality.CANDIDATE))
_register(ToolDefinition("nikto",     "...", phases=["scan"], signal_quality=SignalQuality.CANDIDATE))
_register(ToolDefinition("ffuf",      "...", phases=["recon"],signal_quality=SignalQuality.CANDIDATE))
```

### File: `argus-workers/intelligence_engine.py`

Add priority sort before analysis:

```python
QUALITY_ORDER = {SignalQuality.CONFIRMED: 0, SignalQuality.PROBABLE: 1, SignalQuality.CANDIDATE: 2}

def _sort_findings_for_analysis(self, findings: list[dict]) -> list[dict]:
    from tool_definitions import TOOLS, SignalQuality
    def priority(f):
        tool = TOOLS.get(f.get("source_tool", ""))
        quality = tool.signal_quality if tool else SignalQuality.CANDIDATE
        return QUALITY_ORDER.get(quality, 2)
    return sorted(findings, key=priority)
```

Call this inside `evaluate()` before processing findings through the confidence pipeline.

---

## Idea 2: Tech-Stack-Aware Prompt Injection

### File: `argus-workers/agent/agent_prompts.py`

Add tech threat highlights dict and builder function:

```python
TECH_THREAT_HIGHLIGHTS = {
    "wordpress": """
### WordPress-specific threats
- Plugin CVEs: test /wp-json/wp/v2/users for user enumeration, xmlrpc.php for
  brute force, /wp-admin/admin-ajax.php for unauthenticated actions
- wp-config.php exposure via path traversal or backup file (.bak, ~, .old)
- Shortcode injection in custom post types that render unsanitized HTML
- wp-includes/ms-files.php SSRF on multisite installs
""",
    "react": """
### React/Next.js-specific threats
- dangerouslySetInnerHTML with user-controlled data → stored XSS
- Server Actions without authentication checks → auth bypass
- catch-all routes ([...slug]) without middleware auth → IDOR
- getServerSideProps fetching user-supplied URLs → SSRF
- next.config.js rewrites that expose internal services
""",
    "django": """
### Django-specific threats
- CSRF exemption (@csrf_exempt) on state-changing views
- Raw SQL in .raw() or .extra() with format strings
- Template {{ variable|safe }} disabling auto-escaping
- DEBUG=True leaking settings and stack traces in production
- Missing @login_required on class-based views (CBV)
""",
    "laravel": """
### Laravel-specific threats
- Mass assignment via $fillable omission or $guarded = []
- SQL injection in whereRaw(), selectRaw(), orderByRaw() with user input
- Unvalidated redirects in redirect()->to($request->input('url'))
- Deserialization gadgets in queue jobs with user-controlled payloads
""",
    "express": """
### Express.js-specific threats
- Missing helmet() → no security headers
- res.redirect(req.query.next) without allowlist → open redirect
- CORS misconfiguration with credentials: true + wildcard origin
- prototype pollution via lodash.merge with user-controlled objects
""",
    "go": """
### Go-specific threats
- os/exec.Command() with string concatenation → RCE
- http.Get(userInput) without URL validation → SSRF
- sql.Query() with fmt.Sprintf → SQLi
- goroutine leak from context not cancelled in HTTP handlers
""",
    "java": """
### Java/Spring-specific threats
- @RequestMapping without @PreAuthorize → missing auth
- Runtime.exec() with user-controlled args → RCE
- ObjectInputStream.readObject() on untrusted data → deserialization RCE
- Spring SpEL injection in @Value annotations
""",
    "php": """
### PHP-specific threats
- include/require with user-controlled path → LFI/RFI
- system()/exec()/shell_exec() with user input → RCE
- unserialize() on user data → object injection
- extract($_REQUEST) or $$variable → variable variable injection
""",
}

def build_tech_aware_system_prompt(recon_context) -> str:
    """
    Builds a system prompt enriched with tech-stack-specific threat guidance.
    Called instead of the static TOOL_SELECTION_SYSTEM_PROMPT when a
    ReconContext with tech_stack is available.
    """
    base = TOOL_SELECTION_SYSTEM_PROMPT

    if not recon_context or not recon_context.tech_stack:
        return base

    tech_stack_lower = " ".join(recon_context.tech_stack).lower()
    highlights = []
    for tech_key, highlight in TECH_THREAT_HIGHLIGHTS.items():
        if tech_key in tech_stack_lower:
            highlights.append(highlight)

    if not highlights:
        return base

    tech_section = "\n## Threat highlights for this target's tech stack\n"
    tech_section += "\n".join(highlights[:3])  # max 3 highlights per prompt
    tech_section += "\n"

    # Insert before the tool catalogue
    return base.replace(
        "TOOL CATALOGUE — WEB APPLICATION SCAN",
        tech_section + "\nTOOL CATALOGUE — WEB APPLICATION SCAN"
    )
```

### File: `argus-workers/agent/react_agent.py`

Call `build_tech_aware_system_prompt(recon_context)` instead of using `TOOL_SELECTION_SYSTEM_PROMPT` directly:

```python
# In _get_system_prompt():
def _get_system_prompt(self, recon_context=None) -> str:
    if recon_context and hasattr(recon_context, 'scan_type'):
        if recon_context.scan_type == 'repo':
            return REPO_TOOL_SELECTION_SYSTEM_PROMPT
    return build_tech_aware_system_prompt(recon_context)
```

---

## Idea 3: Requires Gate on Tool Activation

### File: `argus-workers/tool_definitions.py`

Add `ToolRequires` dataclass and `requires` field:

```python
@dataclass
class ToolRequires:
    """Activation condition for a tool — mirrors DeepSec's MatcherGate."""
    tech_contains: list[str] = field(default_factory=list)   # any of these in tech_stack
    recon_signals: list[str] = field(default_factory=list)   # 'has_api', 'has_login_page', 'has_file_upload'
    target_scheme: str | None = None                          # 'https' only

@dataclass
class ToolDefinition:
    # ... existing fields
    requires: ToolRequires | None = None
```

Tag conditional tools:

```python
_register(ToolDefinition("wpscan", ...,
    requires=ToolRequires(tech_contains=["wordpress", "wp-"])))
_register(ToolDefinition("jwt_tool", ...,
    requires=ToolRequires(recon_signals=["has_api", "has_login_page"])))
_register(ToolDefinition("testssl", ...,
    requires=ToolRequires(target_scheme="https")))
_register(ToolDefinition("commix", ...,
    requires=ToolRequires(recon_signals=["has_file_upload"])))  # only if forms found
```

### File: `argus-workers/orchestrator_pkg/scan.py`

Add `_should_run_tool()` and call it before each tool block:

```python
def _should_run_tool(tool_name: str, recon_context, target: str) -> bool:
    from tool_definitions import TOOLS
    tool_def = TOOLS.get(tool_name)
    if not tool_def or not tool_def.requires:
        return True   # no gate → always run
    req = tool_def.requires
    if req.tech_contains:
        stack = " ".join(recon_context.tech_stack).lower() if recon_context else ""
        if not any(t in stack for t in req.tech_contains):
            return False
    if req.recon_signals:
        for signal in req.recon_signals:
            if getattr(recon_context, signal, False):
                return True  # any signal present = run
        return False          # no signal present = skip
    if req.target_scheme:
        if not target.startswith(req.target_scheme):
            return False
    return True
```

Guard each tool dispatch in `execute_scan_tools()` with:

```python
if "wpscan" not in _skip and _should_run_tool("wpscan", recon_context, target):
    # ... run wpscan
```

---

## Idea 4: test\_patterns on YAML Rules

### Files: All 7 `custom_rules/bugbounty_rules/*.yaml`

Add `test_patterns` and `non_matching_patterns` to each rule. Example for IDOR:

```yaml
- id: br_idor_predictable_id
  patterns:
    - regex: "(?i)(\\?|&)(id|user_id|order_id)=\\d+"
  test_patterns:
    - "GET /api/orders?id=12345"
    - "POST /users?user_id=42&action=delete"
    - "/api/v1/invoices?invoice_id=9"
  non_matching_patterns:
    - "GET /api/orders?filter=recent"     # no ID param
    - "/api/orders/uuid-only"              # no ?id= pattern
```

### File: `argus-workers/tests/test_custom_rules_self_validation.py` (NEW)

```python
def test_all_bugbounty_rules_match_their_examples():
    from custom_rules.engine import CustomRuleEngine
    import re
    from pathlib import Path

    rules_dir = Path("custom_rules/bugbounty_rules")
    engine = CustomRuleEngine(str(rules_dir))

    for rule_file in rules_dir.glob("*.yaml"):
        import yaml
        rules = yaml.safe_load(rule_file.read_text()).get("rules", [])
        for rule in rules:
            for test_str in rule.get("test_patterns", []):
                for pattern_entry in rule.get("patterns", []):
                    regex = pattern_entry.get("regex", "")
                    if regex:
                        assert re.search(regex, test_str, re.IGNORECASE), (
                            f"Rule {rule['id']} pattern did not match its own test: {test_str!r}"
                        )
            for non_match in rule.get("non_matching_patterns", []):
                for pattern_entry in rule.get("patterns", []):
                    regex = pattern_entry.get("regex", "")
                    if regex:
                        assert not re.search(regex, non_match, re.IGNORECASE), (
                            f"Rule {rule['id']} falsely matched non-matching example: {non_match!r}"
                        )
```

---

## Idea 5: Structured Target Context Paragraph

### File: `argus-workers/database/repositories/target_profile_repository.py`

Add `to_llm_context_paragraph()`:

```python
def to_llm_context_paragraph(self, profile: dict) -> str:
    """
    Generates a prose paragraph from target profile data for injection into
    the agent prompt. Follows DeepSec's INFO.md pattern — contextual prose
    the LLM can reason from, not a raw data dump.
    """
    if not profile or profile.get("total_scans", 0) == 0:
        return ""

    parts = []
    scans = profile["total_scans"]
    parts.append(f"This target has been scanned {scans} time(s) before.")

    confirmed = profile.get("confirmed_finding_types", [])[:5]
    if confirmed:
        parts.append(
            f"Confirmed vulnerability types in past scans: {', '.join(confirmed)}. "
            f"These warrant immediate focus."
        )

    hot = profile.get("high_value_endpoints", [])[:4]
    if hot:
        parts.append(
            f"Endpoints that produced findings in past scans: {', '.join(hot)}. "
            f"Revisit these first."
        )

    best = [t["tool"] for t in profile.get("best_tools", [])[:3]]
    if best:
        parts.append(f"Tools with confirmed findings on this target: {', '.join(best)}.")

    noisy = profile.get("noisy_tools", [])[:3]
    if noisy:
        parts.append(
            f"Tools that produced only false positives here: {', '.join(noisy)}. "
            f"Run these last."
        )

    tech = profile.get("known_tech_stack", [])[:5]
    if tech:
        parts.append(f"Detected tech stack: {', '.join(tech)}.")

    return " ".join(parts)
```

### File: `argus-workers/agent/agent_prompts.py`

Call `to_llm_context_paragraph()` as the first section of the user prompt when a profile exists, replacing the current static "WHAT WE KNOW ABOUT THIS TARGET" header with real actionable prose.

---

## Idea 6: Formalise the CandidateList Contract

### File: `argus-workers/models/candidate_list.py` (NEW)

```python
from dataclasses import dataclass, field
from enum import Enum

class CandidateSource(str, Enum):
    NUCLEI_CVE     = "nuclei_cve"        # confirmed CVE template match
    NUCLEI_MISC    = "nuclei_misc"        # misconfiguration template
    DALFOX         = "dalfox"             # XSS hit
    SQLMAP         = "sqlmap"             # SQLi confirmed
    WEB_SCANNER    = "web_scanner"        # custom check
    RECON_ENDPOINT = "recon_endpoint"     # endpoint discovered, not yet tested
    CUSTOM_RULE    = "custom_rule"        # YAML rule match

@dataclass
class Candidate:
    """A specific location that warrants AI investigation."""
    endpoint: str
    source: CandidateSource
    vuln_slug: str              # e.g. 'sql-injection', 'xss', 'idor'
    snippet: str                # raw tool output that flagged this
    line_hint: str | None = None
    confidence: float = 0.5

@dataclass
class CandidateList:
    """
    The structured output of the scan phase — input to the AI analysis phase.
    Formalises the contract between deterministic tool execution and LLM reasoning.
    """
    target: str
    candidates: list[Candidate] = field(default_factory=list)

    def by_quality(self) -> list[Candidate]:
        """Return candidates sorted by signal quality — confirmed first."""
        order = {
            CandidateSource.NUCLEI_CVE: 0,
            CandidateSource.SQLMAP: 0,
            CandidateSource.DALFOX: 1,
            CandidateSource.WEB_SCANNER: 1,
            CandidateSource.NUCLEI_MISC: 2,
            CandidateSource.CUSTOM_RULE: 2,
            CandidateSource.RECON_ENDPOINT: 3,
        }
        return sorted(self.candidates, key=lambda c: order.get(c.source, 3))

    def to_llm_summary(self) -> str:
        """Compact summary for injection into the agent user prompt."""
        by_slug: dict[str, list[Candidate]] = {}
        for c in self.candidates:
            by_slug.setdefault(c.vuln_slug, []).append(c)

        lines = [f"=== SCAN CANDIDATES ({len(self.candidates)} total) ==="]
        for slug, cands in sorted(by_slug.items()):
            endpoints = list({c.endpoint for c in cands})[:3]
            lines.append(f"{slug}: {len(cands)} hit(s) on {', '.join(endpoints)}")
        return "\n".join(lines)
```

### Integration point

The scan phase populates a `CandidateList` from tool results. The agent receives `candidate_list.to_llm_summary()` as a structured section in its user prompt rather than reconstructing this from raw tool output. This makes the agent's reasoning grounded in concrete, structured data rather than prose interpretation of tool output.

### File: `argus-workers/orchestrator_pkg/orchestrator.py`

At the handoff from scan to agent:

```python
# Old: findings = execute_scan_tools(ctx, ...); agent.receive(findings)
# New:
candidates = CandidateList.from_findings(findings)
agent.receive(candidates.to_llm_summary())
```

---

## Verification

### Idea 1
- Unit test: confirm sort order groups CONFIRMED before CANDIDATE findings.
- Integration test: full scan with nuclei + nikto, verify nuclei findings hit analyze phase first.

### Idea 2
- Capture system prompt on a WordPress scan → verify WordPress-specific threats appear.
- Capture system prompt on a Go repo scan → verify Go-specific threats appear.
- Capture system prompt on a target with no recognized tech → verify no tech section injected (failsafe).

### Idea 3
- Scan non-WordPress → assert wpscan is skipped.
- Scan HTTP target → assert testssl is skipped.
- Scan Python-only repo → assert only bandit + pip_audit run.

### Idea 4
- `pytest tests/test_custom_rules_self_validation.py` → passes.
- Break a regex in `idor.yaml` → test fails with exact rule ID and test string.

### Idea 5
- Scan a target with prior scans → capture prompt, verify "WHAT WE KNOW" is prose paragraph.
- Scan a first-time target → verify no stale info injected.

### Idea 6
- Capture agent observation history → verify structured candidate summary (by vuln slug, counts) instead of raw output dump.
- Verify `CandidateList.by_quality()` sorts confirmed first.
