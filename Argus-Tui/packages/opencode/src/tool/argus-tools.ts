/**
 * Argus Security Tools — native OpenCode tool definitions for all 16 agent-internal tools.
 *
 * Each tool runs the corresponding Python script directly via subprocess,
 * same as how bash/grep/glob run native commands. No MCP bridge needed.
 */
import { Effect, Schema } from "effect"
import * as Tool from "./tool"
import { join, dirname } from "path"
import { fileURLToPath } from "url"
import { accessSync, constants } from "fs"
import { execFileSync } from "child_process"

/**
 * Shared parameters for all argus tools.
 */
const TargetParam = Schema.String.annotate({ description: "Target URL or scope to assess" })
const ExtraParam = Schema.optional(
  Schema.String.annotate({ description: 'JSON-encoded extra parameters (e.g. {"tech_stack":["apache"]})' }),
)

/**
 * Map of native tool IDs to their MCP tool names (Python scripts).
 */
const TOOL_SCRIPT_NAMES: Record<string, string> = {
  "finding-correlation-engine": "finding_correlation_engine",
  "attack-path-generator": "attack_path_generator",
  "verification-agent": "verification_agent",
  "browser-security-operator": "browser_security_operator",
  "attack-surface-mapper": "attack_surface_mapper",
  "evidence-intelligence-engine": "evidence_intelligence_engine",
  "executive-report-generator": "executive_report_generator",
  "threat-intelligence-aggregator": "threat_intelligence_aggregator",
  "vulnerability-knowledge-engine": "vulnerability_knowledge_engine",
  "secure-code-intelligence-engine": "secure_code_intelligence_engine",
  "infrastructure-security-analyzer": "infrastructure_security_analyzer",
  "assessment-orchestrator": "assessment_orchestrator",
  "workflow-intelligence-engine": "workflow_intelligence_engine",
  "engagement-analytics-engine": "engagement_analytics_engine",
  register: "register",
  login: "login",
}

/**
 * Find the project root by walking up from this file's location.
 * This file is at: Argus-Tui/packages/opencode/src/tool/argus-tools.ts
 * Project root is: Argus Cli/ (parent of Argus-Tui/ and argus-workers/)
 */
function findProjectRoot(): string {
  // Start from this file's directory
  let dir = dirname(fileURLToPath(import.meta.url))
  // Walk up until we find a directory containing both Argus-Tui and argus-workers
  for (let i = 0; i < 10; i++) {
    try {
      accessSync(join(dir, "argus-workers", "mcp_server.py"), constants.R_OK)
      return dir  // Found it — dir contains argus-workers/
    } catch {
      dir = dirname(dir)  // Go up one level
    }
  }
  return ""
}

/**
 * Run an Argus tool script via subprocess.
 */
async function runToolScript(toolName: string, target: string, extra: string): Promise<{
  success: boolean; data: string; error: string; durationMs: number
}> {
  const start = Date.now()
  const projectRoot = findProjectRoot()
  if (!projectRoot) {
    return {
      success: false, data: "", error: "Could not locate Argus project root (expected argus-workers/mcp_server.py in parent directories)",
      durationMs: Date.now() - start,
    }
  }

  const runnerScript = join(projectRoot, "argus-workers", "tools", "run_agent_tool.py")
  try {
    accessSync(runnerScript, constants.R_OK)
  } catch {
    return {
      success: false, data: "", error: `Runner script not found or not readable: ${runnerScript}`,
      durationMs: Date.now() - start,
    }
  }

  try {
    const args = [runnerScript, toolName, "--target", target]
    if (extra) {
      args.push("--extra", extra)
    }
    const stdout = execFileSync("python3", args, {
      encoding: "utf-8",
      timeout: 120_000,
      maxBuffer: 10 * 1024 * 1024,
    })
    const parsed = JSON.parse(stdout)
    return {
      success: parsed.success ?? true,
      data: parsed.data || JSON.stringify(parsed.findings || [], null, 2),
      error: parsed.error || "",
      durationMs: Date.now() - start,
    }
  } catch (e: any) {
    // Try to parse partial output on failure
    if (e.stdout) {
      try {
        const parsed = JSON.parse(e.stdout)
        return {
          success: false,
          data: JSON.stringify(parsed.findings || [], null, 2),
          error: parsed.error || e.message,
          durationMs: Date.now() - start,
        }
      } catch {}
    }
    return {
      success: false, data: "", error: e.message,
      durationMs: Date.now() - start,
    }
  }
}

/**
 * Factory to create an Argus tool definition.
 * Each tool runs the Python script directly via subprocess — no MCP bridge needed.
 */
function defineArgusTool(id: string, description: string) {
  const Parameters = Schema.Struct({
    target: TargetParam,
    extra: ExtraParam,
  })

  return Tool.define(
    id,
    Effect.gen(function* () {
      return {
        description,
        parameters: Parameters,
        execute: (params: Schema.Schema.Type<typeof Parameters>, ctx: Tool.Context) =>
          Effect.gen(function* () {
            const scriptName = TOOL_SCRIPT_NAMES[id] ?? id
            const result = yield* Effect.promise(() =>
              runToolScript(scriptName, params.target, params.extra || "")
            )
            return {
              title: `${id} completed`,
              output: result.error
                ? `${id} completed with issues:\n${result.error}\n\n${result.data || ""}`
                : result.data || "No output",
              metadata: { tool: id, duration: result.durationMs, success: result.success },
            }
          }).pipe(Effect.orDie),
      }
    }),
  )
}

// ── Tool Exports ──────────────────────────────────────────────

export const FindingCorrelationEngineTool = defineArgusTool(
  "finding-correlation-engine",
  "Correlates findings: semantic deduplication, root cause analysis, attack chain detection, priority ranking. Use after assessments to clean up duplicate findings.",
)

export const AttackPathGeneratorTool = defineArgusTool(
  "attack-path-generator",
  "Generates attack paths from findings: builds asset graph, finds exploitable paths, scores by risk, generates narrative. Use to understand how findings chain together.",
)

export const VerificationAgentTool = defineArgusTool(
  "verification-agent",
  "Verifies findings by attempting reproduction: replays exploits, collects evidence, scores confidence, promotes confirmed findings. Use to confirm vulnerabilities are real.",
)

export const BrowserSecurityOperatorTool = defineArgusTool(
  "browser-security-operator",
  "Browser-based security testing: runs Playwright for BOLA detection, XSS verification, privilege escalation checks. Requires credentials.",
)

export const AttackSurfaceMapperTool = defineArgusTool(
  "attack-surface-mapper",
  "Maps attack surface: subdomain discovery, port scanning, URL discovery, asset graph construction. Use for initial reconnaissance.",
)

export const EvidenceIntelligenceEngineTool = defineArgusTool(
  "evidence-intelligence-engine",
  "Analyzes and enriches evidence: extracts metadata, correlates across findings, generates intelligence summaries.",
)

export const ExecutiveReportGeneratorTool = defineArgusTool(
  "executive-report-generator",
  "Generates executive security reports: non-technical summaries, risk scoring, remediation roadmap, compliance mapping.",
)

export const ThreatIntelligenceAggregatorTool = defineArgusTool(
  "threat-intelligence-aggregator",
  "Aggregates threat intelligence: CVE lookup, EPSS scoring, known exploit status, threat actor profiling.",
)

export const VulnerabilityKnowledgeEngineTool = defineArgusTool(
  "vulnerability-knowledge-engine",
  "Vulnerability knowledge base queries: CWE mapping, remediation suggestions, exploit database references.",
)

export const SecureCodeIntelligenceEngineTool = defineArgusTool(
  "secure-code-intelligence-engine",
  "Secure code analysis: checks for OWASP Top 10 violations, secure coding patterns, dependency vulnerabilities.",
)

export const InfrastructureSecurityAnalyzerTool = defineArgusTool(
  "infrastructure-security-analyzer",
  "Infrastructure security analysis: cloud config review, network segmentation checks, identity/perimeter audit.",
)

export const AssessmentOrchestratorTool = defineArgusTool(
  "assessment-orchestrator",
  "Coordinates full assessment lifecycle: plans phases, sequences tools, manages state transitions across recon/scan/analyze/report.",
)

export const WorkflowIntelligenceEngineTool = defineArgusTool(
  "workflow-intelligence-engine",
  "Workflow intelligence: analyzes assessment patterns, suggests optimizations, detects coverage gaps in workflows.",
)

export const EngagementAnalyticsEngineTool = defineArgusTool(
  "engagement-analytics-engine",
  "Engagement analytics: tracks assessment metrics, identifies trends, generates engagement summaries and comparison reports.",
)

export const RegisterTool = defineArgusTool(
  "register",
  "Auto-creates accounts: discovers registration forms, generates credentials, submits registration, handles retries and email verification.",
)

export const LoginTool = defineArgusTool(
  "login",
  "Auto-authenticates: discovers login forms, submits credentials, captures session cookies/JWT, handles 2FA detection and rate limiting.",
)
