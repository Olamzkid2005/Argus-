import type { PhaseExecutionRequest, PhaseExecutionResult, NormalizedFinding, ErrorRecovery } from "./types"
import { Capability } from "./capabilities"
import { ToolRegistry } from "../workflows/tool-registry"
import { WorkersBridge } from "../bridge/mcp-client"
import { ConfidenceEngine } from "../engagement/confidence"
import { ApprovalService } from "../workflows/approval"
import type { ApprovalGate } from "../workflows/types"
import { WorkflowRegistry } from "../workflows/registry"
import type { EvidenceCollector } from "../evidence/collector"
import type { BrowserEngine } from "../browser/engine"
import { Feature, type FeatureFlags } from "../config/feature-flags"

export interface PhaseExecutor {
  execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult>
}

export interface BrowserVerifierDeps {
  evidenceCollector: EvidenceCollector
  engine: BrowserEngine
  credentials: Record<string, { username: string; password: string }>
  targetUrl: string
}

const RECOVERY_LABELS: Record<ErrorRecovery, string> = {
  retry_once_then_skip: "retry once then skip",
  skip_and_continue: "skip and continue",
  fail_fast: "fail fast",
}

export class InProcessExecutor implements PhaseExecutor {
  private approvalService: ApprovalService
  private requiredGates: ApprovalGate[] = []
  private browserDeps: BrowserVerifierDeps | null = null
  private featureFlags: FeatureFlags | null = null
  private phaseCount = 0

  constructor(
    private toolRegistry: ToolRegistry,
    private bridge: WorkersBridge,
    private confidenceEngine: ConfidenceEngine,
    private workflowRegistry?: WorkflowRegistry,
  ) {
    this.approvalService = new ApprovalService()
  }

  setBrowserVerifierDeps(deps: BrowserVerifierDeps): void {
    this.browserDeps = deps
  }

  setFeatureFlags(flags: FeatureFlags): void {
    this.featureFlags = flags
  }

  /** Check whether a feature is enabled (defaults true if no flag system attached) */
  private isFeatureEnabled(feature: Feature): boolean {
    return this.featureFlags?.isEnabled(feature) ?? true
  }

  private gatesLoaded = false

  loadGates(workflowName: string): void {
    const workflow = this.workflowRegistry?.getWorkflow(workflowName)
    this.requiredGates = this.approvalService.getRequiredGates(workflow?.approval_required)
    this.gatesLoaded = true
  }

  async execute(phase: PhaseExecutionRequest): Promise<PhaseExecutionResult> {
    if (!this.gatesLoaded) {
      throw new Error("loadGates must be called before execute")
    }

    this.phaseCount++

    // Periodic MCP drift check: every 5 phases, run a lightweight capability
    // hash comparison. On mismatch, run the full detectDrift() and log.
    if (this.phaseCount % 5 === 0) {
      try {
        const inSync = await this.bridge.quickDriftCheck()
        if (!inSync) {
          const drift = await this.bridge.detectDrift()
          if (drift.missing_from_mcp.length > 0 || drift.missing_from_registry.length > 0 || drift.capability_gaps.length > 0) {
            console.warn(`[executor] MCP drift detected at phase ${phase.phaseId}:`, JSON.stringify(drift))
          }
        }
      } catch {
        // Drift check is advisory — never fail a phase for it
      }
    }

    const gate = this.isFeatureEnabled(Feature.APPROVAL_GATES)
      ? this.approvalService.needsApproval(phase, this.requiredGates)
      : null
    if (gate) {
      const result = await this.approvalService.requestApproval(gate, phase.phaseId, phase.target)
      if (!result.approved) {
        return {
          phaseId: phase.phaseId,
          status: "skipped",
          findings: [],
          artifacts: [],
          errors: [result.reason ?? "Skipped by user"],
          durationMs: 0,
        }
      }
    }

    const startTime = Date.now()
    const findings: NormalizedFinding[] = []
    const errors: string[] = []
    const calledTools = new Set<string>()

    for (const cap of phase.requiredCapabilities) {
      const tools = this.toolRegistry.getToolsByCapability(cap)
      if (tools.length === 0) {
        errors.push(`No tools available for capability: ${cap}`)
        continue
      }

      for (const tool of tools) {
        if (calledTools.has(tool.name)) continue
        calledTools.add(tool.name)

        const errorRecovery = this.resolveErrorRecovery(phase, tool.name)
        let lastError: Error | null = null
        let success = false

        for (let attempt = 1; attempt <= 2; attempt++) {
          try {
            const result = await this.bridge.callTool(tool.name, {
              target: phase.target,
              capability: cap,
              config: phase.config,
            })

            if (result.success && result.data) {
              const data = result.data
              if (!Array.isArray(data)) {
                errors.push(`Tool ${tool.name} returned non-array result`)
              } else {
                for (const finding of data) {
                  const promoted = this.confidenceEngine.promote(finding)
                  findings.push({ ...finding, confidence: promoted })
                }
                success = true
                break
              }
            }

            lastError = new Error(result.error ?? "Tool returned unsuccessful result")
            if (errorRecovery === "fail_fast") {
              errors.push(`Tool ${tool.name} failed (fail_fast): ${lastError.message}`)
              return {
                phaseId: phase.phaseId,
                status: "failed",
                findings,
                artifacts: [],
                errors,
                durationMs: Date.now() - startTime,
              }
            }

            if (errorRecovery === "retry_once_then_skip" && attempt === 1) {
              continue
            }

            break
          } catch (error) {
            lastError = error as Error
            if (errorRecovery === "fail_fast") {
              errors.push(`Tool ${tool.name} failed (fail_fast): ${lastError.message}`)
              return {
                phaseId: phase.phaseId,
                status: "failed",
                findings,
                artifacts: [],
                errors,
                durationMs: Date.now() - startTime,
              }
            }

            if (errorRecovery === "retry_once_then_skip" && attempt === 1) {
              continue
            }

            break
          }
        }

        if (!success && lastError) {
          errors.push(`Tool ${tool.name} failed after ${errorRecovery === "retry_once_then_skip" ? "1 retry" : "no retry"} (${RECOVERY_LABELS[errorRecovery]}): ${lastError.message}`)
        }
      }
    }

    // Run browser verifiers if phase requires BROWSER_VERIFICATION capability
    // Task 4.1: Feature flag gate — BROWSER_VERIFICATION must be enabled
    if (
      this.browserDeps &&
      this.isFeatureEnabled(Feature.BROWSER_VERIFICATION) &&
      phase.requiredCapabilities.includes(Capability.BROWSER_VERIFICATION)
    ) {
      try {
        const browserFindings = await this.runBrowserVerifiers(phase.target)
        findings.push(...browserFindings)
      } catch (error) {
        errors.push(`Browser verification failed: ${(error as Error).message}`)
      }
    }

    return {
      phaseId: phase.phaseId,
      status: errors.length > 0 && findings.length > 0 ? "partial" : errors.length > 0 && findings.length === 0 ? "failed" : findings.length > 0 ? "completed" : "partial",
      findings,
      artifacts: [],
      errors,
      durationMs: Date.now() - startTime,
    }
  }

  private async runBrowserVerifiers(target: string): Promise<NormalizedFinding[]> {
    const { evidenceCollector, engine, credentials, targetUrl } = this.browserDeps!
    const findings: NormalizedFinding[] = []
    const { BOLAVerifier } = await import("../browser/verifiers/bola")
    const { StoredXSSVerifier } = await import("../browser/verifiers/xss")
    const { PrivilegeEscalationVerifier } = await import("../browser/verifiers/priv-esc")
    const { VerificationRunner } = await import("../browser/verifiers/runner")

    const verifiers: { verifier: import("../browser/types").VerificationScenario; roleName: string }[] = []

    // BOLA verifier — needs attacker + victim roles
    if (credentials.attacker && credentials.victim) {
      verifiers.push({
        verifier: new BOLAVerifier(engine, targetUrl, "/api/resource", credentials.attacker, credentials.victim),
        roleName: "bola",
      })
    }

    // Stored XSS verifier — needs at least one set of creds
    if (credentials.user || credentials.admin) {
      const creds = credentials.user ?? credentials.admin!
      verifiers.push({
        verifier: new StoredXSSVerifier(engine, targetUrl, targetUrl, "<script>alert('xss')</script>"),
        roleName: "xss",
      })
    }

    // Privilege escalation verifier — needs low-priv user + admin target
    if (credentials.user) {
      verifiers.push({
        verifier: new PrivilegeEscalationVerifier(engine, targetUrl, ["/admin"], credentials.user),
        roleName: "priv-esc",
      })
    }

    if (verifiers.length === 0) {
      return findings
    }

    const runner = new VerificationRunner()
    for (const { verifier, roleName } of verifiers) {
      try {
        const result = runner.run(verifier)
        const vResult = await result

        // Capture evidence after verifier runs (engine still alive at this point)
        const evidencePkg = await verifier.collectEvidence()
        const findingId = `find-${roleName}-${Date.now()}`
        const artifacts: import("../evidence/types").ArtifactEntry[] = []

        // Take a final evidence screenshot of the target
        try {
          const ctx = await engine.createContext()
          const page = await ctx.newPage()
          await page.goto(targetUrl, { waitUntil: "networkidle" })
          const shot = await engine.captureScreenshot(page)
          const entry = await evidenceCollector.captureScreenshot(target, findingId, shot)
          artifacts.push(entry)
          await page.close()
          await ctx.close()
        } catch { console.warn("[executor] evidence screenshot failed") }

        if (artifacts.length > 0) {
          await evidenceCollector.createPackage(target, findingId, artifacts)
        }

        if (vResult.passed) {
          const finding: NormalizedFinding = {
            id: findingId,
            title: `${verifier.name}: ${vResult.summary}`,
            severity: 3, // HIGH
            confidence: vResult.confidence,
            status: "CONFIRMED",
            description: vResult.summary,
            evidence: [{
              packageId: `pkg-${roleName}-${Date.now()}`,
              findingId,
              artifacts: artifacts.map(a => ({ path: a.path, type: a.type })),
              packageHash: "",
              createdAt: evidencePkg.createdAt,
            }],
            tool: `browser-verifier/${roleName}`,
            phase: "verification",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
          findings.push(finding)
        }
      } catch (error) {
        console.warn(`[executor] verifier error: ${(error as Error).message}`)
        continue
      }
    }

    return findings
  }

  private resolveErrorRecovery(phase: PhaseExecutionRequest, toolName: string): ErrorRecovery {
    const tool = this.toolRegistry.getTool(toolName)
    if (tool?.destructive) return "fail_fast"
    if (tool?.requires_auth) return "skip_and_continue"
    return "retry_once_then_skip"
  }
}
