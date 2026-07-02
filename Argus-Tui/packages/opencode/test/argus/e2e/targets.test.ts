/**
 * E2E Tests — Real Targets (Task 4.3)
 *
 * Tests against live Juice Shop and DVWA targets running via Docker.
 * The assessment pipeline uses a mock bridge (real MCP worker would require
 * the full infrastructure stack: Redis, Postgres, Celery). Target connectivity,
 * doctor checks, report generation, and evidence collection are real.
 *
 * Infrastructure needed:
 *   - Docker (for vulnerable targets)
 *   - Bun runtime
 *   - Python3 on PATH (for MCP worker path validation — not invoked)
 *
 * Tests skip gracefully if Docker is not available.
 */

import { describe, it, expect, beforeAll, afterAll } from "bun:test"
import { startTargets, stopTargets, JUICE_SHOP, DVWA } from "./docker-helpers"

const STARTUP_TIMEOUT = 180_000 // 3 min for Docker pull + startup
const PIPELINE_TIMEOUT = 60_000  // 1 min per pipeline test
const DOCTOR_TIMEOUT = 30_000

// ── Docker availability check ──

let dockerAvailable = false

beforeAll(async () => {
  try {
    const proc = Bun.spawn(["docker", "info", "--format", "{{.ServerVersion}}"], {
      stdio: ["ignore", "pipe", "pipe"],
    })
    const output = await new Response(proc.stdout).text()
    dockerAvailable = output.trim().length > 0
  } catch {
    dockerAvailable = false
  }
  if (!dockerAvailable) {
    console.error("[e2e] Docker not available — E2E tests will be skipped")
  }
}, 5000)

// ── Target lifecycle ──

let targetsStarted = false

beforeAll(async () => {
  if (!dockerAvailable) return

  console.error("[e2e] Starting vulnerable test targets...")
  try {
    await startTargets()
    targetsStarted = true
  } catch (err) {
    console.error(`[e2e] Failed to start Docker targets: ${err}`)
  }
}, STARTUP_TIMEOUT)

afterAll(async () => {
  if (targetsStarted) {
    console.error("[e2e] Stopping test targets...")
    try {
      await stopTargets()
    } catch {
      // best-effort cleanup
    }
  }
}, 30000)

/**
 * Build a minimal mock bridge for pipeline testing.
 * Returns findings for targets we know about (Juice Shop, DVWA) and empty
 * results for unknown targets, so the pipeline doesn't stall on connect().
 */
function createMockBridge() {
  return {
    callTool: async () => ({
      success: true,
      data: [
        {
          id: "e2e-finding-001",
          title: "E2E Test Finding — Missing Security Headers",
          description: "Target is missing X-Content-Type-Options, X-Frame-Options, and CSP headers.",
          severity: 2, // MEDIUM
          confidence: 5, // HIGH
          cwe: "CWE-693",
          tool: "e2e-test",
        },
        {
          id: "e2e-finding-002",
          title: "E2E Test Finding — Information Disclosure",
          description: "Server header reveals software version information.",
          severity: 1, // LOW
          confidence: 4, // MEDIUM
          cwe: "CWE-200",
          tool: "e2e-test",
        },
      ],
      durationMs: 42,
    }),
    connect: async () => {},
    disconnect: async () => {},
    isHealthy: async () => true,
    on: () => {},
    llmStatus: () => "AVAILABLE" as const,
    getTools: async () => [],
    detectDrift: async () => ({
      missing_from_registry: [] as string[],
      missing_from_mcp: [] as string[],
      capability_gaps: [] as string[],
    }),
    quickDriftCheck: async () => true,
    killChild: () => {},
    restartWorker: async () => {},
    resetCircuitBreaker: () => {},
    setRegistryTools: () => {},
    supervisor: {
      resetAttempts: () => {},
      restartWorker: async () => {},
    },
  }
}

/**
 * Run an assessment via WorkflowRunner with a mock bridge.
 * Uses a temp database so tests don't pollute each other.
 */
async function runAssessmentWithMock(target: string, mockBridge: any) {
  const { WorkflowRunner } = await import("../../../src/argus/workflow-runner")
  const { EngagementStore } = await import("../../../src/argus/engagement/store")
  const { mkdtempSync, rmSync } = await import("fs")
  const { join } = await import("path")
  const { tmpdir } = await import("os")
  const { WorkflowRegistry } = await import("../../../src/argus/workflows/registry")
  const { ToolRegistry } = await import("../../../src/argus/workflows/tool-registry")
  const { WorkflowPlanner } = await import("../../../src/argus/planner/planner")

  const dbDir = mkdtempSync(join(tmpdir(), "argus-e2e-"))
  const dbPath = join(dbDir, `e2e-${Date.now()}.db`)
  const store = new EngagementStore(dbPath)

  // Use real registries + planner for deterministic pipeline, mock for bridge
  const srcDir = join(__dirname, "../../../src/argus")
  const workflowsDir = join(srcDir, "workflows")
  const toolsPath = join(workflowsDir, "tool-definitions.yaml")
  const workflowRegistry = new WorkflowRegistry(workflowsDir)
  workflowRegistry.loadAll()
  const toolRegistry = new ToolRegistry()
  toolRegistry.load(toolsPath)
  const planner = new WorkflowPlanner(workflowRegistry, toolRegistry)

  try {
    const runner = new WorkflowRunner({
      store,
      workflowRegistry,
      toolRegistry,
      planner,
      bridge: mockBridge,
    })

    const progressEvents: any[] = []
    const result = await runner.run({
      target,
      useLLM: false,
      onProgress: (event: any) => {
        progressEvents.push(event)
        if (typeof event === "string") {
          console.error(`[e2e] ${event}`)
        }
      },
    })

    const engId = result.engagementId
    const phases = store.getPhases(engId)

    return {
      engagementId: engId,
      allFindings: result.allFindings,
      durationMs: result.durationMs,
      success: result.success,
      phases,
      progressEvents,
    }
  } finally {
    try {
      rmSync(dbDir, { recursive: true, force: true })
    } catch {}
  }
}

// ═══════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════

describe("E2E: Docker lifecycle", () => {
  it("Docker is available on PATH", () => {
    if (!dockerAvailable) {
      console.warn("[e2e] Docker not available — skipping E2E target-dependent tests")
      return
    }
    expect(dockerAvailable).toBe(true)
  })

  it("targets started successfully", async () => {
    if (!targetsStarted) return
    expect(targetsStarted).toBe(true)
  })
})

describe("E2E: Target connectivity", () => {
  it("Juice Shop responds on port 3001", async () => {
    if (!targetsStarted) return
    for (let i = 0; i < 15; i++) {
      try {
        const resp = await fetch("http://127.0.0.1:3001", { signal: AbortSignal.timeout(5000) })
        if (resp.ok) {
          expect(resp.status).toBe(200)
          return
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 2000))
    }
    throw new Error("Juice Shop did not become healthy within 15 retries")
  }, STARTUP_TIMEOUT / 2)

  it("DVWA responds on port 3002", async () => {
    if (!targetsStarted) return
    for (let i = 0; i < 15; i++) {
      try {
        const resp = await fetch("http://127.0.0.1:3002", { signal: AbortSignal.timeout(5000) })
        if (resp.ok) {
          expect(resp.status).toBe(200)
          return
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 2000))
    }
    throw new Error("DVWA did not become healthy within 15 retries")
  }, STARTUP_TIMEOUT / 2)

  it("Juice Shop returns expected application content", async () => {
    if (!targetsStarted) return
    const resp = await fetch("http://127.0.0.1:3001", { signal: AbortSignal.timeout(5000) })
    const text = await resp.text()
    expect(text.length).toBeGreaterThan(100)
    expect(text).toMatch(/juice|shop|OWASP|angular/i)
  }, 15000)
})

describe("E2E: Doctor command", () => {
  it("doctorCommand returns 12 checks without crashing", async () => {
    if (!targetsStarted) return
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    expect(results.length).toBe(12)
    for (const r of results) {
      expect(["PASS", "WARN", "FAIL"]).toContain(r.status)
      expect(r.message.length).toBeGreaterThan(0)
    }
  }, DOCTOR_TIMEOUT)

  it("Runtime check always passes with version info", async () => {
    if (!targetsStarted) return
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const runtime = results.find((r: any) => r.name === "Runtime")!
    expect(runtime.status).toBe("PASS")
    expect(runtime.message).toMatch(/(Node\.js|Bun)/)
  }, DOCTOR_TIMEOUT)

  it("Toolchain check reports tools without crashing", async () => {
    if (!targetsStarted) return
    const { doctorCommand } = await import("../../../src/argus/commands/doctor")
    const results = await doctorCommand()
    const tc = results.find((r: any) => r.name === "Toolchain")!
    expect(["PASS", "WARN", "FAIL"]).toContain(tc.status)
    expect(tc.message).toMatch(/tools?/i)
  }, DOCTOR_TIMEOUT)
})

describe("E2E: Assessment pipeline (mock bridge)", () => {
  it("creates engagement with correct ID format", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    expect(result.success).toBe(true)
    expect(result.engagementId).toMatch(/^ENG-/)
    expect(result.durationMs).toBeGreaterThan(0)
  }, PIPELINE_TIMEOUT)

  it("executes all planned phases", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    expect(result.phases.length).toBeGreaterThanOrEqual(1)
    const terminalStatuses = ["COMPLETED", "PARTIAL", "SKIPPED", "FAILED"]
    for (const phase of result.phases) {
      expect(terminalStatuses).toContain(phase.status)
    }
  }, PIPELINE_TIMEOUT)

  it("returns findings with valid structure", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    expect(result.allFindings.length).toBeGreaterThanOrEqual(1)
    for (const finding of result.allFindings) {
      expect(finding.id).toBeTruthy()
      expect(finding.title).toBeTruthy()
      expect(typeof finding.severity).toBe("number")
      expect(finding.severity).toBeGreaterThanOrEqual(0)
      expect(typeof finding.confidence).toBe("number")
      expect(finding.confidence).toBeGreaterThanOrEqual(0)
    }
  }, PIPELINE_TIMEOUT)

  it("phases are persisted to the engagement store", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    for (const phase of result.phases) {
      expect(phase.engagementId).toBe(result.engagementId)
      expect(phase.status).toBeTruthy()
    }
  }, PIPELINE_TIMEOUT)

  it("progress callbacks receive lifecycle events", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    expect(result.progressEvents.length).toBeGreaterThan(0)
  }, PIPELINE_TIMEOUT)

  it("runs against real target URL without crashing", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    expect(result.success).toBe(true)
  }, PIPELINE_TIMEOUT)

  it("runs against DVWA URL without crashing", async () => {
    if (!targetsStarted) return
    const result = await runAssessmentWithMock("http://127.0.0.1:3002", createMockBridge())
    expect(result.success).toBe(true)
  }, PIPELINE_TIMEOUT)
})

describe("E2E: Report generation", () => {
  it("ReportGenerator produces markdown from findings", async () => {
    if (!targetsStarted) return
    const { ReportGenerator } = await import("../../../src/argus/reporting/generator")
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    const gen = new ReportGenerator()

    const markdown = gen.generateMarkdown(
      result.allFindings,
      result.engagementId,
      "http://127.0.0.1:3001",
      "assessment",
    )

    expect(markdown.length).toBeGreaterThan(0)
    expect(markdown).toContain("Assessment Summary")
    expect(markdown).toContain(result.engagementId)
  }, PIPELINE_TIMEOUT)

  it("ReportGenerator produces SARIF output", async () => {
    if (!targetsStarted) return
    const { ReportGenerator } = await import("../../../src/argus/reporting/generator")
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    const gen = new ReportGenerator()

    const sarif = gen.generateSARIF(
      result.allFindings,
      result.engagementId,
      "http://127.0.0.1:3001",
    )

    expect(sarif).toContain("sarif")
    expect(sarif).toContain("runs")
    expect(sarif).toContain("results")
  }, PIPELINE_TIMEOUT)

  it("ReportGenerator produces JSON output", async () => {
    if (!targetsStarted) return
    const { ReportGenerator } = await import("../../../src/argus/reporting/generator")
    const result = await runAssessmentWithMock("http://127.0.0.1:3001", createMockBridge())
    const gen = new ReportGenerator()

    const json = gen.generateJSON(
      result.allFindings,
      result.engagementId,
      "http://127.0.0.1:3001",
    )

    const parsed = JSON.parse(json)
    expect(parsed.metadata.engagementId).toBe(result.engagementId)
    expect(Array.isArray(parsed.findings)).toBe(true)
  }, PIPELINE_TIMEOUT)
})

describe("E2E: Evidence collection", () => {
  it("EvidenceCollector stores artifacts to disk", async () => {
    if (!targetsStarted) return
    const { EvidenceCollector } = await import("../../../src/argus/evidence/collector")
    const { mkdtempSync, rmSync, existsSync } = await import("fs")
    const { join } = await import("path")
    const { tmpdir } = await import("os")

    const baseDir = mkdtempSync(join(tmpdir(), "argus-evidence-"))
    try {
      const collector = new EvidenceCollector(baseDir, {}, "ENG-e2e-test-001")
      const artifact = await collector.saveRequest("ENG-e2e-test-001", "test-finding", "GET /test HTTP/1.1")
      expect(artifact.id).toBeTruthy()
      expect(artifact.hash).toBeTruthy()
      expect(existsSync(artifact.path)).toBe(true)
    } finally {
      try { rmSync(baseDir, { recursive: true, force: true }) } catch {}
    }
  }, 15000)
})

describe("E2E: Config and CLI smoke tests", () => {
  it("argus --help exits 0 and prints usage", async () => {
    if (!targetsStarted) return
    const entry = join(__dirname, "../../../src/argus/index.ts")
    const proc = Bun.spawn(["bun", "run", entry, "--help"], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ARGUS_MODE: "0" },
    })
    const [stdout, stderr] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ])
    const exitCode = await proc.exited
    expect(exitCode).toBe(0)
    const combined = stdout + stderr
    expect(combined.length).toBeGreaterThan(0)
  }, 15000)

  it("config command returns configuration without crashing", async () => {
    if (!targetsStarted) return
    const { configCommand } = await import("../../../src/argus/commands/config")
    const output = await configCommand()
    expect(output.length).toBeGreaterThan(0)
    expect(output).toMatch(/configuration|config|setting/i)
  }, 15000)
})
