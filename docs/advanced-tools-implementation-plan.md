# Argus Advanced Security Tools — Implementation Plan

## How the 11 Tool Types Are Used in the Codebase

Before mapping to security tools, here's how each tool type is used in the current architecture:

| Tool Type | Current Usage | Location |
|-----------|--------------|----------|
| **bash** (subprocess) | `ToolRunner.run()` executes security binaries via `subprocess.run()`. `AsyncToolRunner` uses `asyncio.create_subprocess_exec()`. MCP server uses `subprocess.run()` for direct tool execution. | `tools/tool_runner.py:394`, `tool_core/sandbox.py:131`, `mcp_server.py:340` |
| **edit** (file editing) | Not used as a security tool. Configuration files are edited manually. Tool definitions are static YAML/dataclass. | N/A for tool system |
| **glob** (file finding) | `ToolRegistry._resolve()` scans augmented PATH to find tool binaries. MCP server globs `tools/definitions/*.yaml` at startup. | `tool_core/registry.py:131`, `mcp_server.py:183` |
| **grep** (content search) | Parsers grep through tool output to extract findings. `ToolRunner` validates args against dangerous patterns. | `parsers/parser.py`, `tools/tool_runner.py:65` |
| **question** (asking questions) | LLM agent asks the LLM to decide next tool. `ReActAgent` builds prompts with context, LLM returns `AgentAction` with tool choice. | `agent/react_agent.py:314`, `agent/agent_prompts.py` |
| **read** (reading files) | MCP server reads YAML tool definitions at startup. Tool definitions loaded from `tool_definitions.py`. | `mcp_server.py:183`, `tool_definitions.py` |
| **skill** (loading skills) | `ReActAgent._ensure_phase_tools()` loads phase-specific tool sets. `CoordinatorAgent` creates phase-specific agents. | `agent/react_agent.py:82`, `agent/coordinator.py:56` |
| **task** (launching sub-agents) | `SwarmOrchestrator` launches parallel specialist agents (IDORAgent, AuthAgent, APIAgent). `CoordinatorAgent` delegates phases. | `agent/swarm.py:483`, `agent/coordinator.py:90` |
| **todowrite** (task tracking) | `ProgressTracker` tracks phase completion. `StreamingFindingEmitter` emits real-time progress. | `tasks/progress_tracker.py`, `streaming.py` |
| **webfetch** (fetching web content) | Web scanners fetch target content via HTTP. `WebScanner`, `APIScanner`, `BrowserScanner` all fetch web content. | `tools/web_scanner.py`, `tools/api_scanner.py`, `tools/browser_scanner.py` |
| **write** (writing files) | Findings saved to SQLite via `FindingRepository`. Reports generated to files. Evidence packages stored on disk. | `database/repositories/finding_repository.py`, `orchestrator_pkg/reporting/` |

---

## Architecture: How New Tools Must Fit

Every new tool must integrate with **three registration paths** (kept in sync):

```
┌─────────────────────────────────────────────────────────┐
│  PATH 1: Python YAML (tools/definitions/*.yaml)        │
│  → MCP Server loads at startup                          │
│  → Builds CLI commands, validates args                  │
├─────────────────────────────────────────────────────────┤
│  PATH 2: Python tool_definitions.py                    │
│  → ReActAgent uses for LLM context (68 tools)          │
│  → Provides descriptions to agent for planning          │
├─────────────────────────────────────────────────────────┤
│  PATH 3: TypeScript tool-definitions.yaml              │
│  → Planner uses for capability matching                 │
│  → Scores confidence/coverage for ranking               │
└─────────────────────────────────────────────────────────┘
```

New tools must also integrate with the **execution layer**:

```
┌─────────────────────────────────────────────────────────┐
│  For binary tools (subprocess-based):                   │
│  → ToolRunner.run() or AsyncToolRunner.run()            │
│  → MCP Bridge registers with MCP server                 │
│  → Tool is callable via call_tool()                     │
├─────────────────────────────────────────────────────────┤
│  For Python-based tools (no binary):                    │
│  → Implement AbstractTool or AsyncTool                  │
│  → Use FindingBuilder for structured findings           │
│  → Register in ToolRegistry                             │
│  → Callable via tool_core.sandbox                       │
├─────────────────────────────────────────────────────────┤
│  For composite/multi-tool tools:                        │
│  → Implement as SpecialistAgent subclass                │
│  → Use SwarmOrchestrator for parallel execution         │
│  → Aggregate findings from sub-tools                    │
│  → Return UnifiedToolResult with merged findings        │
└─────────────────────────────────────────────────────────┘
```

---

## Tool-by-Tool Implementation Plan

### Phase 1: Core Security Tools (Highest Value)

---

### 1. Browser Security Operator

**Complexity:** Very High | **Value:** Extremely High

**What it replaces:** BrowserScanner (basic) + manual BOLA/XSS/PrivEsc verification + 10 separate tool calls

**Current state:** `BrowserScanner` in `tools/browser_scanner.py` runs Playwright in a subprocess but only does basic SPA detection. The TypeScript side has `browser/verifiers/` with BOLA, XSS, and PrivEsc verifiers, but they're disconnected from the Python tool system.

**Architecture:**
```
BrowserSecurityOperator (Python, AsyncTool)
├── PlaywrightManager (persistent browser context)
├── AuthManager (login, session handling, token capture)
├── DOMAnalyzer (form discovery, CSP analysis, JS secrets)
├── XSSVerifier (reflection testing, CSP bypass attempts)
├── CSRFVerifier (token validation, origin checks)
├── PrivilegeEscalator (role switching, endpoint enumeration)
└── EvidenceCollector (screenshots, HAR, request/response pairs)
```

**Implementation approach:**
1. Extend `BrowserScanner` into `BrowserSecurityOperator` (AsyncTool subclass)
2. Use Playwright persistent context (not subprocess) for session continuity
3. Integrate with `AuthManager` already in `tools/auth_manager.py`
4. Return findings via `FindingBuilder` with evidence artifacts
5. Add `BROWSER_SECURITY` capability to TypeScript capabilities enum

**Files to create/modify:**
- `tools/browser_security_operator.py` (new — AsyncTool subclass)
- `tools/browser_security_operator_auth.py` (new — auth state management)
- `tools/browser_security_operator_verifiers.py` (new — XSS/CSRF/PrivEsc)
- `tools/definitions/browser_security_operator.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `BROWSER_SECURITY`)

**Key design decisions:**
- Use `asyncio` Playwright API (not subprocess) for session persistence
- Each verifier runs as a sub-task within the operator
- Evidence collected via `EvidenceCollector` (screenshots, HAR files)
- Credentials passed via `ToolContext.dual_auth` (existing pattern)

**Estimated files:** 6 new, 4 modified

---

### 2. Attack Surface Mapper

**Complexity:** High | **Value:** Extremely High

**What it replaces:** 8 independent tool runs (subfinder, amass, dnsx, httpx, naabu, katana, gau, waybackurls)

**Current state:** Each tool runs independently in `orchestrator_pkg/recon.py`. No unified output. Findings scattered across multiple parsers.

**Architecture:**
```
AttackSurfaceMapper (Python, AbstractTool)
├── SubdomainDiscovery (subfinder + amass + dnsx)
├── PortDiscovery (naabu)
├── WebProbing (httpx)
├── URLDiscovery (katana + gau + waybackurls)
├── TechnologyFingerprinting (httpx + whatweb)
├── APIEndpointDiscovery (katana + arjun)
└── AssetGraph (unified asset model)
```

**Implementation approach:**
1. Create `AttackSurfaceMapper` as `AbstractTool` subclass
2. Internally call existing tools via `ToolRunner.run()` (not subprocess directly)
3. Merge results into unified `AssetGraph` data structure
4. Deduplicate subdomains, ports, URLs across tools
5. Add `ASSET_DISCOVERY` capability to TypeScript

**Files to create/modify:**
- `tools/attack_surface_mapper.py` (new — AbstractTool subclass)
- `tools/attack_surface/` (new — subdirectory for sub-modules)
  - `subdomain_discovery.py`
  - `port_discovery.py`
  - `web_probing.py`
  - `url_discovery.py`
  - `asset_graph.py`
- `tools/definitions/attack_surface_mapper.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `ASSET_DISCOVERY`)

**Key design decisions:**
- Uses existing `ToolRunner` internally (not raw subprocess)
- Results cached in `AssetGraph` to avoid re-scanning
- Parallel execution via `ThreadPoolExecutor` for sub-tools
- Output format: unified JSON with `domains`, `subdomains`, `ports`, `technologies`, `historical_urls`, `api_endpoints`

**Estimated files:** 7 new, 4 modified

---

### Phase 2: Evidence & Reporting Tools

---

### 3. Evidence Intelligence Engine

**Complexity:** High | **Value:** High

**What it replaces:** Ad-hoc evidence collection scattered across verifiers

**Current state:** `EvidenceCollector` exists in `evidence/collector.ts` (TypeScript side) but Python side has no equivalent. Evidence is manually attached to findings.

**Architecture:**
```
EvidenceIntelligenceEngine (Python, AbstractTool)
├── ScreenshotCapture (Playwright-based)
├── RequestStorage (HAR + raw request/response)
├── ArtifactHasher (SHA-256 chain of custody)
├── EvidenceScorer (reliability scoring)
└── ChainOfCustody (audit trail)
```

**Implementation approach:**
1. Create `EvidenceIntelligenceEngine` as `AbstractTool`
2. Accept findings as input, enrich with evidence
3. Hash all artifacts for integrity verification
4. Score evidence reliability (0-100)
5. Return enriched findings with evidence packages

**Files to create/modify:**
- `tools/evidence_intelligence_engine.py` (new)
- `tools/evidence/` (new — subdirectory)
  - `screenshot_capture.py`
  - `request_storage.py`
  - `artifact_hasher.py`
  - `evidence_scorer.py`
  - `chain_of_custody.py`
- `tools/definitions/evidence_intelligence_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 7 new, 3 modified

---

### 4. Executive Report Generator

**Complexity:** Medium | **Value:** High

**What it replaces:** Manual report assembly in `orchestrator_pkg/reporting/`

**Current state:** `ReportGenerationService` exists but generates basic reports. No executive summary, no attack path visualization, no PDF output.

**Architecture:**
```
ExecutiveReportGenerator (Python, AbstractTool)
├── FindingAggregator (group by severity/CWE/asset)
├── AttackPathVisualizer (graph → text/SVG)
├── ExecutiveSummaryGenerator (LLM-assisted)
├── ReportRenderer (PDF + Markdown + HTML)
└── RemediationAdvisor (CWE → fix mapping)
```

**Implementation approach:**
1. Create `ExecutiveReportGenerator` as `AbstractTool`
2. Accept all findings as input
3. Use LLM for executive summary generation
4. Render to multiple formats (PDF, Markdown, HTML)
5. Include attack path narratives

**Files to create/modify:**
- `tools/executive_report_generator.py` (new)
- `tools/report/` (new — subdirectory)
  - `finding_aggregator.py`
  - `attack_path_visualizer.py`
  - `executive_summary.py`
  - `report_renderer.py`
  - `remediation_advisor.py`
- `tools/definitions/executive_report_generator.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 7 new, 3 modified

---

### Phase 3: Intelligence & Research Tools

---

### 5. Threat Intelligence Aggregator

**Complexity:** High | **Value:** High

**What it replaces:** Manual OSINT, separate Shodan/Censys/VirusTotal lookups

**Current state:** `IntelligenceEngine` exists in `intelligence_engine.py` but focuses on CVE/EPSS enrichment. No multi-source aggregation.

**Architecture:**
```
ThreatIntelligenceAggregator (Python, AbstractTool)
├── ShodanClient (API integration)
├── CensysClient (API integration)
├── VirusTotalClient (API integration)
├── AbuseIPDBClient (API integration)
├── CRTSHClient (certificate transparency)
├── WHOISClient (domain info)
├── IntelligenceMerger (dedup + confidence scoring)
└── ResultNormalizer (unified output format)
```

**Implementation approach:**
1. Create `ThreatIntelligenceAggregator` as `AbstractTool`
2. Query multiple sources in parallel
3. Merge and deduplicate results
4. Score confidence per source
5. Return unified intelligence report

**Files to create/modify:**
- `tools/threat_intelligence_aggregator.py` (new)
- `tools/intel/` (new — subdirectory)
  - `shodan_client.py`
  - `censys_client.py`
  - `virustotal_client.py`
  - `abuseipdb_client.py`
  - `crtsh_client.py`
  - `whois_client.py`
  - `intel_merger.py`
- `tools/definitions/threat_intelligence_aggregator.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `THREAT_INTELLIGENCE`)

**Estimated files:** 10 new, 4 modified

---

### 6. Vulnerability Knowledge Engine

**Complexity:** Medium | **Value:** High

**What it replaces:** Manual CVE/CWE lookups, separate ExploitDB searches

**Current state:** `IntelligenceEngine` does CVE/EPSS but no CAPEC, OWASP, or ExploitDB integration.

**Architecture:**
```
VulnerabilityKnowledgeEngine (Python, AbstractTool)
├── CVELookup (NVD API)
├── CWELookup (MITRE CWE)
├── CAPECLookup (attack patterns)
├── OWASPLookup (Top 10 mapping)
├── ExploitDBLookup (exploit search)
├── KnowledgeGraph (cross-reference engine)
└── RemediationMapper (vuln → fix)
```

**Implementation approach:**
1. Create `VulnerabilityKnowledgeEngine` as `AbstractTool`
2. Query NVD, MITRE, ExploitDB APIs
3. Build knowledge graph connecting CVE→CWE→CAPEC→OWASP
4. Map findings to remediation guidance
5. Return enriched vulnerability profiles

**Files to create/modify:**
- `tools/vulnerability_knowledge_engine.py` (new)
- `tools/knowledge/` (new — subdirectory)
  - `cve_lookup.py`
  - `cwe_lookup.py`
  - `capec_lookup.py`
  - `owasp_lookup.py`
  - `exploitdb_lookup.py`
  - `knowledge_graph.py`
  - `remediation_mapper.py`
- `tools/definitions/vulnerability_knowledge_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 9 new, 3 modified

---

### Phase 4: AI-Native Security Tools

---

### 7. Finding Correlation Engine

**Complexity:** High | **Value:** Extremely High

**What it replaces:** Manual finding deduplication, no attack chain detection

**Current state:** No correlation engine exists. Findings are stored independently. Deduplication is basic (hash-based).

**Architecture:**
```
FindingCorrelationEngine (Python, AbstractTool)
├── Deduplicator (semantic similarity, not just hash)
├── RootCauseAnalyzer (group by underlying cause)
├── AttackChainDetector (finding → finding paths)
├── ImpactAggregator (combined CVSS scoring)
└── PriorityRanker (exploitability × impact × evidence)
```

**Implementation approach:**
1. Create `FindingCorrelationEngine` as `AbstractTool`
2. Accept list of findings as input
3. Use embedding-based similarity for deduplication
4. Detect attack chains via dependency graph
5. Return correlated findings with chains

**Files to create/modify:**
- `tools/finding_correlation_engine.py` (new)
- `tools/correlation/` (new — subdirectory)
  - `deduplicator.py`
  - `root_cause_analyzer.py`
  - `attack_chain_detector.py`
  - `impact_aggregator.py`
  - `priority_ranker.py`
- `tools/definitions/finding_correlation_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `FINDING_CORRELATION`)

**Estimated files:** 7 new, 4 modified

---

### 8. Attack Path Generator

**Complexity:** Very High | **Value:** Extremely High

**What it replaces:** Manual attack path documentation in reports

**Current state:** `ChainExploitGenerator` exists in `chain_exploit_generator.py` but is basic. No graph-based path generation.

**Architecture:**
```
AttackPathGenerator (Python, AbstractTool)
├── AssetGraphBuilder (from findings + assets)
├── PathFinder (Dijkstra/BFS on attack graph)
├── PathScorer (likelihood × impact)
├── PathVisualizer (graph → text/SVG/Mermaid)
└── NarrativeGenerator (LLM-assisted storytelling)
```

**Implementation approach:**
1. Create `AttackPathGenerator` as `AbstractTool`
2. Build attack graph from findings, assets, roles
3. Find shortest/highest-impact paths from entry to crown jewels
4. Generate narrative explanations via LLM
5. Return paths with visualizations

**Files to create/modify:**
- `tools/attack_path_generator.py` (new)
- `tools/attack_paths/` (new — subdirectory)
  - `asset_graph_builder.py`
  - `path_finder.py`
  - `path_scorer.py`
  - `path_visualizer.py`
  - `narrative_generator.py`
- `tools/definitions/attack_path_generator.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `ATTACK_PATH_GENERATION`)

**Estimated files:** 7 new, 4 modified

---

### Phase 5: Developer & Architecture Tools

---

### 9. Secure Code Intelligence Engine

**Complexity:** High | **Value:** High

**What it replaces:** Running semgrep, bandit, gitleaks, trivy separately

**Current state:** Each SAST/SCA tool runs independently in `orchestrator_pkg/repo_scan.py`. No unified code review.

**Architecture:**
```
SecureCodeIntelligenceEngine (Python, AbstractTool)
├── SecretScanner (gitleaks + trufflehog)
├── SASTScanner (semgrep + bandit + gosec)
├── DependencyScanner (trivy + npm-audit + pip-audit)
├── SCAGenerator (SBOM generation)
├── CodeFlowAnalyzer (taint tracking)
└── UnifiedReport (merged findings by category)
```

**Implementation approach:**
1. Create `SecureCodeIntelligenceEngine` as `AbstractTool`
2. Run all code scanners in parallel
3. Merge findings by category (secrets, SAST, SCA)
4. Generate unified SBOM
5. Return categorized findings

**Files to create/modify:**
- `tools/secure_code_intelligence_engine.py` (new)
- `tools/code_intel/` (new — subdirectory)
  - `secret_scanner.py`
  - `sast_scanner.py`
  - `dependency_scanner.py`
  - `sbom_generator.py`
  - `code_flow_analyzer.py`
- `tools/definitions/secure_code_intelligence_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 7 new, 3 modified

---

### 10. Infrastructure Security Analyzer

**Complexity:** High | **Value:** High

**What it replaces:** Manual IaC review, separate Docker/K8s/Terraform scans

**Current state:** No IaC security analysis exists in the codebase.

**Architecture:**
```
InfrastructureSecurityAnalyzer (Python, AbstractTool)
├── TerraformAnalyzer (tfsec/checkov)
├── KubernetesAnalyzer (kube-score/kubeaudit)
├── DockerAnalyzer (trivy image scan)
├── SBOMAnalyzer (dependency vulnerabilities)
├── MisconfigurationDetector (CIS benchmarks)
└── InfrastructureAttackPath (cloud misconfig → exploit)
```

**Implementation approach:**
1. Create `InfrastructureSecurityAnalyzer` as `AbstractTool`
2. Detect IaC type from file extensions
3. Run appropriate scanners for each type
4. Map misconfigurations to attack paths
5. Return unified infrastructure findings

**Files to create/modify:**
- `tools/infrastructure_security_analyzer.py` (new)
- `tools/infra/` (new — subdirectory)
  - `terraform_analyzer.py`
  - `kubernetes_analyzer.py`
  - `docker_analyzer.py`
  - `sbom_analyzer.py`
  - `misconfig_detector.py`
  - `infra_attack_path.py`
- `tools/definitions/infrastructure_security_analyzer.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `INFRASTRUCTURE_SECURITY`)

**Estimated files:** 8 new, 4 modified

---

### Phase 6: Multi-Agent & Orchestration Tools

---

### 11. Assessment Orchestrator

**Complexity:** Very High | **Value:** High

**What it replaces:** `CoordinatorAgent` + manual phase management

**Current state:** `CoordinatorAgent` delegates to `ReActAgent.create_for_phase()` but doesn't coordinate specialist agents or manage parallel execution.

**Architecture:**
```
AssessmentOrchestrator (Python, SpecialistAgent)
├── PhaseManager (recon → scan → deep_scan → analyze → report)
├── AgentPool (parallel specialist agents)
├── ResourceManager (tool concurrency, rate limiting)
├── DecisionLogger (every tool choice recorded)
├── ProgressTracker (real-time phase status)
└── AdaptivePlanner (LLM adjusts plan based on findings)
```

**Implementation approach:**
1. Create `AssessmentOrchestrator` as `SpecialistAgent` subclass
2. Extend `SwarmOrchestrator` with phase management
3. Add adaptive planning (LLM can modify remaining phases)
4. Implement resource-aware scheduling
5. Return comprehensive assessment results

**Files to create/modify:**
- `tools/assessment_orchestrator.py` (new)
- `tools/orchestration/` (new — subdirectory)
  - `phase_manager.py`
  - `agent_pool.py`
  - `resource_manager.py`
  - `adaptive_planner.py`
- `tools/definitions/assessment_orchestrator.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 6 new, 3 modified

---

### 12. Verification Agent

**Complexity:** High | **Value:** Extremely High

**What it replaces:** Manual finding verification, basic browser verifiers

**Current state:** TypeScript has `browser/verifiers/` with BOLA, XSS, PrivEsc but they're disconnected. Python has `tools/finding_verifier.py` but it's basic.

**Architecture:**
```
VerificationAgent (Python, AsyncTool)
├── FindingReceiver (accepts unverified findings)
├── ReproductionEngine (replays attack)
├── EvidenceCollector (screenshots, request/response)
├── ConfidenceScorer (evidence-based scoring)
├── FindingPromoter (PENDING → CONFIRMED/REJECTED)
└── ReportGenerator (verification report)
```

**Implementation approach:**
1. Create `VerificationAgent` as `AsyncTool` subclass
2. Accept findings from any scanner
3. Attempt reproduction via Playwright or HTTP
4. Collect evidence and score confidence
5. Promote or reject findings

**Files to create/modify:**
- `tools/verification_agent.py` (new)
- `tools/verification/` (new — subdirectory)
  - `reproduction_engine.py`
  - `evidence_collector.py`
  - `confidence_scorer.py`
  - `finding_promoter.py`
- `tools/definitions/verification_agent.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)
- `Argus-Tui/.../capabilities.ts` (add `FINDING_VERIFICATION`)

**Estimated files:** 6 new, 4 modified

---

### Phase 7: Operational Tools

---

### 13. Workflow Intelligence Engine

**Complexity:** Medium | **Value:** Medium

**What it replaces:** Manual performance analysis, no tool failure tracking

**Current state:** `ToolMetricsRepository` exists but no analysis engine.

**Architecture:**
```
WorkflowIntelligenceEngine (Python, AbstractTool)
├── ExecutionProfiler (per-tool timing)
├── FailureAnalyzer (error pattern detection)
├── BottleneckDetector (phase-level analysis)
├── PerformanceRecommender (workflow optimization)
└── DashboardData (metrics aggregation)
```

**Implementation approach:**
1. Create `WorkflowIntelligenceEngine` as `AbstractTool`
2. Query `ToolMetricsRepository` for historical data
3. Analyze execution patterns
4. Recommend workflow optimizations
5. Return analytics dashboard data

**Files to create/modify:**
- `tools/workflow_intelligence_engine.py` (new)
- `tools/analytics/` (new — subdirectory)
  - `execution_profiler.py`
  - `failure_analyzer.py`
  - `bottleneck_detector.py`
  - `performance_recommender.py`
- `tools/definitions/workflow_intelligence_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 6 new, 3 modified

---

### 14. Engagement Analytics Engine

**Complexity:** Medium | **Value:** Medium

**What it replaces:** No cross-engagement analytics exist

**Current state:** Findings stored per-engagement. No cross-engagement analysis.

**Architecture:**
```
EngagementAnalyticsEngine (Python, AbstractTool)
├── FindingAggregator (cross-engagement stats)
├── TrendAnalyzer (temporal patterns)
├── BenchmarkGenerator (org-wide metrics)
├── RiskCalculator (portfolio risk scoring)
└── ReportGenerator (analytics report)
```

**Implementation approach:**
1. Create `EngagementAnalyticsEngine` as `AbstractTool`
2. Query all engagements from database
3. Aggregate findings across engagements
4. Generate trend analysis and benchmarks
5. Return analytics report

**Files to create/modify:**
- `tools/engagement_analytics_engine.py` (new)
- `tools/analytics/` (shared with WorkflowIntelligenceEngine)
  - `finding_aggregator.py`
  - `trend_analyzer.py`
  - `benchmark_generator.py`
  - `risk_calculator.py`
- `tools/definitions/engagement_analytics_engine.yaml` (new)
- `tool_definitions.py` (add `_register()`)
- `Argus-Tui/.../tool-definitions.yaml` (add entry)

**Estimated files:** 5 new, 3 modified

---

## New Capabilities to Add to TypeScript

```typescript
// Argus-Tui/packages/opencode/src/argus/shared/capabilities.ts
export enum Capability {
  // ... existing 19 capabilities ...
  
  // New capabilities for advanced tools
  BROWSER_SECURITY = "browser_security",
  ASSET_DISCOVERY = "asset_discovery",
  EVIDENCE_COLLECTION = "evidence_collection",
  REPORT_GENERATION_ADVANCED = "report_generation_advanced",
  THREAT_INTELLIGENCE = "threat_intelligence",
  VULNERABILITY_KNOWLEDGE = "vulnerability_knowledge",
  FINDING_CORRELATION = "finding_correlation",
  ATTACK_PATH_GENERATION = "attack_path_generation",
  CODE_INTELLIGENCE = "code_intelligence",
  INFRASTRUCTURE_SECURITY = "infrastructure_security",
  ASSESSMENT_ORCHESTRATION = "assessment_orchestration",
  FINDING_VERIFICATION = "finding_verification",
  WORKFLOW_ANALYTICS = "workflow_analytics",
  ENGAGEMENT_ANALYTICS = "engagement_analytics",
}
```

---

## Implementation Order (Priority)

| Priority | Tool | Complexity | Value | Dependencies |
|----------|------|-----------|-------|--------------|
| 1 | Finding Correlation Engine | High | Extremely High | None |
| 2 | Attack Path Generator | Very High | Extremely High | Finding Correlation |
| 3 | Verification Agent | High | Extremely High | BrowserSecurityOperator |
| 4 | Browser Security Operator | Very High | Extremely High | Playwright |
| 5 | Attack Surface Mapper | High | Extremely High | Existing tools |
| 6 | Executive Report Generator | Medium | High | Finding Correlation |
| 7 | Threat Intelligence Aggregator | High | High | API keys |
| 8 | Vulnerability Knowledge Engine | Medium | High | NVD API |
| 9 | Secure Code Intelligence Engine | High | High | Existing SAST tools |
| 10 | Infrastructure Security Analyzer | High | High | IaC detection |
| 11 | Evidence Intelligence Engine | High | High | Playwright |
| 12 | Assessment Orchestrator | Very High | High | All specialist agents |
| 13 | Workflow Intelligence Engine | Medium | Medium | ToolMetricsRepository |
| 14 | Engagement Analytics Engine | Medium | Medium | Database |

---

## Files Checklist (All Tools Combined)

### New Files (Total: ~80)

**Tool implementations:** 14 main files
**Sub-modules:** ~50 files across subdirectories
**YAML definitions:** 14 files
**Tests:** ~20 files (1 per tool + integration tests)

### Modified Files (Total: ~15)

| File | Changes |
|------|---------|
| `tool_definitions.py` | Add 14 `_register()` calls |
| `Argus-Tui/.../tool-definitions.yaml` | Add 14 tool entries |
| `Argus-Tui/.../capabilities.ts` | Add 14 capability enums |
| `Argus-Tui/.../tool-registry.ts` | Update capability mappings |
| `Argus-Tui/.../executor.ts` | Support new capabilities |
| `tools/mcp_bridge.py` | Register new tools |
| `agent/react_agent.py` | Add new phase tools |
| `agent/swarm.py` | Add new specialist agents |
| `orchestrator_pkg/orchestrator.py` | Wire new tools |
| `orchestrator_pkg/scan.py` | Add new scan phases |

---

## Testing Strategy

Each tool must have:

1. **Unit tests** (`tests/test_tool_<name>.py`)
   - Mock external dependencies (APIs, subprocess)
   - Test core logic in isolation
   - Test error handling paths

2. **Integration tests** (`tests/test_tool_<name>_integration.py`)
   - Test with real ToolRunner (mocked subprocess)
   - Test MCP server registration
   - Test TypeScript planner selection

3. **E2E tests** (`tests/near_infinite/test_e2e_<name>.py`)
   - Test full assessment pipeline with new tool
   - Test finding correlation across tools
   - Test report generation end-to-end

---

## Security Considerations

1. **API key management:** All external API calls must use `SecretsManager` for key storage
2. **Rate limiting:** All API clients must respect rate limits
3. **Scope validation:** All tools must validate target scope before execution
4. **Credential isolation:** API keys must not leak to subprocesses (already handled by `ToolRunner._locked_env()`)
5. **Evidence integrity:** All evidence must be hashed for chain of custody
6. **Audit logging:** All tool executions must be logged to decision repository
