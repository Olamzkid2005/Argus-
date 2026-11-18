import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"
import { canResume } from "../../../../src/argus/engagement/recovery"

let dbDir: string

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-resume-test-"))
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

function makeStore(name: string): EngagementStore {
  return new EngagementStore(join(dbDir, `${name}.db`))
}

describe("resume validation", () => {
  test("canResume returns true for RUNNING engagement", () => {
    const store = makeStore("running")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(canResume(loaded!)).toBe(true)
  })

  test("canResume returns true for PAUSED engagement", () => {
    const store = makeStore("paused")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "PAUSED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(canResume(loaded!)).toBe(true)
  })

  test("canResume returns false for COMPLETED engagement", () => {
    const store = makeStore("completed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "COMPLETED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(canResume(loaded!)).toBe(false)
  })

  test("canResume returns false for FAILED engagement", () => {
    const store = makeStore("failed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "FAILED")
    const loaded = store.getEngagement(eng.id)
    expect(loaded).not.toBeNull()
    expect(canResume(loaded!)).toBe(false)
  })

  test("getPhases returns phases for an engagement", () => {
    const store = makeStore("phases")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.savePhases(eng.id, [
      {
        id: "phase-recon", engagementId: eng.id, name: "recon", status: "COMPLETED",
        capabilities: ["web_recon"], executionMode: "sequential", replanCycle: false,
      },
      {
        id: "phase-scan", engagementId: eng.id, name: "scan", status: "PENDING",
        capabilities: ["vulnerability_scanning"], executionMode: "sequential", replanCycle: false,
      },
    ])
    const phases = store.getPhases(eng.id)
    expect(phases).toHaveLength(2)
    expect(phases[0].name).toBe("recon")
  })

  test("saveFindings and getFindings round-trips correctly", () => {
    const store = makeStore("findings")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.saveFindings(eng.id, [{
      id: "find-1", title: "XSS", severity: 3, confidence: 2,
      status: "PENDING", description: "test", tool: "nuclei", phase: "scan",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    }])
    const findings = store.getFindings(eng.id)
    expect(findings).toHaveLength(1)
    expect(findings[0].title).toBe("XSS")
  })

  test("appendAuditLog creates retrievable entries", () => {
    const store = makeStore("audit")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.appendAuditLog(eng.id, "TEST", "test event")
    const log = store.getAuditLog(eng.id)
    expect(log.length).toBeGreaterThanOrEqual(1)
  })

  test("engagement can be updated from CREATED to RUNNING to COMPLETED", () => {
    const store = makeStore("status")
    const eng = store.createEngagement("https://example.com", "assessment")
    expect(eng.status).toBe("CREATED")
    store.updateStatus(eng.id, "RUNNING")
    expect(store.getEngagement(eng.id)!.status).toBe("RUNNING")
    store.updateStatus(eng.id, "COMPLETED")
    expect(store.getEngagement(eng.id)!.status).toBe("COMPLETED")
  })

  test("resumeCommand returns not-found message for non-existent engagement", async () => {
    const store = makeStore("nonexistent-eng")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand("ENG-NONEXISTENT", { storeOverride: store })
    expect(result).toContain("Engagement not found")
  })

  test("resumeCommand returns cannot-resume message for COMPLETED engagement", async () => {
    const store = makeStore("already-completed")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "COMPLETED")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
  })

  test("resumeCommand returns cannot-resume message for FAILED engagement", async () => {
    const store = makeStore("failed-eng")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "FAILED")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
  })

  test("resumeCommand returns cannot-resume message for CREATED engagement", async () => {
    const store = makeStore("created-eng")
    const eng = store.createEngagement("https://test.com", "assessment")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
  })

  // This test requires MCP worker infrastructure and times out without it.
  // Skipped by default — run with --timeout=60000 to test resume functionality.
  test.skip("resumeCommand returns success message for RUNNING engagement", async () => {
    const store = makeStore("happy-resume")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).not.toContain("cannot be resumed")
    expect(result).not.toContain("Engagement not found")
  })
})

describe("resumeCommand degradation reporting", () => {
  async function seedResume(
    storeName: string,
    options: { planDegradations?: string[] } = {},
  ) {
    const { buildCheckpoint } = await import("../../../../src/argus/engagement/checkpoint")
    const { scopeEntriesFor } = await import("../../../../src/argus/browser/scope-guard")

    const store = makeStore(storeName)
    const engagement = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(engagement.id, "INTERRUPTED")

    const started = new Date(Date.parse(engagement.createdAt) + 1000).toISOString()
    const plan = {
      workflow: "full_assessment",
      phases: [
        {
          phaseId: "phase-recon",
          name: "recon",
          workflowName: "full_assessment",
          target: "https://example.com",
          requiredCapabilities: [],
          config: {},
          previousPhaseResults: [],
          toolExecution: "sequential" as const,
          replanCycle: true,
        },
        {
          phaseId: "phase-scan",
          name: "sqlmap",
          workflowName: "full_assessment",
          target: "https://example.com",
          requiredCapabilities: [],
          config: {},
          previousPhaseResults: [],
          toolExecution: "sequential" as const,
          replanCycle: true,
        },
      ],
      errorRecovery: {},
      planCreatedAt: "2026-11-14T10:00:00.000Z",
      ...(options.planDegradations ? { degradations: options.planDegradations } : {}),
    }
    const phases = [
      {
        id: "phase-recon",
        engagementId: engagement.id,
        name: "recon",
        status: "COMPLETED" as const,
        capabilities: [],
        executionMode: "sequential" as const,
        replanCycle: true,
        startedAt: started,
        completedAt: new Date(Date.parse(started) + 1000).toISOString(),
      },
      {
        id: "phase-scan",
        engagementId: engagement.id,
        name: "sqlmap",
        status: "PENDING" as const,
        capabilities: [],
        executionMode: "sequential" as const,
        replanCycle: true,
      },
    ]
    store.savePhases(engagement.id, phases)
    store.saveCheckpoint(
      buildCheckpoint({
        engagement,
        plan: plan as never,
        phases,
        scope: scopeEntriesFor(engagement.target),
        budgetUsage: {
          llmCalls: 0,
          llmFailures: 0,
          inputTokens: 0,
          outputTokens: 0,
          costUsd: 0,
          costKnown: true,
          toolCalls: 1,
          requestCount: 0,
        },
        startedAt: started,
        now: new Date(Date.parse(started) + 2000),
      }),
    )
    return { store, engagement }
  }

  const bridge = { connect: async () => {}, disconnect: async () => {} }

  function executorReturning(result: Record<string, unknown>) {
    return {
      loadGates() {},
      setOnProgress() {},
      async execute(phase: { phaseId: string }) {
        return {
          phaseId: phase.phaseId,
          findings: [],
          artifacts: [],
          errors: [],
          durationMs: 0,
          ...result,
        } as never
      },
    }
  }

  test("emits degradation lines for skipped coverage and failed phases", async () => {
    const { store, engagement } = await seedResume("resume-degraded", {
      planDegradations: ["reporting (no installed tool for report_generation)"],
    })
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const progress: string[] = []

    const result = await resumeCommand(engagement.id, {
      storeOverride: store,
      bridgeOverride: bridge,
      executorOverride: executorReturning({ status: "failed", errors: ["sqlmap boom"] }),
      onProgress: (event) => {
        if (typeof event === "string") progress.push(event)
      },
    })

    const lines = progress.join("\n")
    expect(lines).toContain("Resume completed with 2 degraded step(s)")
    expect(lines).toContain("capability-missing: reporting (no installed tool for report_generation)")
    expect(lines).toContain("phase-failed: sqlmap failed and was skipped: sqlmap boom")

    // The caller prints the returned string, so it must carry the list too.
    expect(result).toContain("## Degraded coverage (2 step(s))")
    expect(result).toContain("phase-failed: sqlmap failed and was skipped: sqlmap boom")

    // Audit trail records it, and the run is not reported as a clean COMPLETED.
    expect(
      store.getAuditLog(engagement.id).some(
        (entry) => entry.eventType === "RUN_DEGRADED" && entry.message.includes("phase-failed"),
      ),
    ).toBe(true)
    expect(store.getEngagement(engagement.id)!.status).toBe("PARTIAL")
  })

  test("prints degradation lines to stderr with no onProgress passed, like `assess`", async () => {
    // `argus resume` calls resumeCommand(id) with no options, so this is the
    // exact path the CLI takes: the lines must reach stderr anyway.
    const { store, engagement } = await seedResume("resume-cli-degraded", {
      planDegradations: ["reporting (no installed tool for report_generation)"],
    })
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")

    const errChunks: string[] = []
    const originalWrite = process.stderr.write
    process.stderr.write = ((chunk: string | Uint8Array) => {
      errChunks.push(String(chunk))
      return true
    }) as typeof process.stderr.write

    let result: string
    try {
      result = await resumeCommand(engagement.id, {
        storeOverride: store,
        bridgeOverride: bridge,
        executorOverride: executorReturning({ status: "failed", errors: ["sqlmap boom"] }),
      })
    } finally {
      process.stderr.write = originalWrite
    }

    const stderr = errChunks.join("")
    // Same shape as `assess`: one summary line, then a bullet per degradation.
    expect(stderr).toContain("⚠ Resume completed with 2 degraded step(s) — coverage is incomplete:")
    expect(stderr).toContain("  • capability-missing: reporting (no installed tool for report_generation)")
    expect(stderr).toContain("  • phase-failed: sqlmap failed and was skipped: sqlmap boom")
    // The report on stdout still carries the section for the written artifact.
    expect(result).toContain("## Degraded coverage (2 step(s))")
  })

  test("a clean resumed run emits no degradation lines", async () => {
    const { store, engagement } = await seedResume("resume-clean")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const progress: string[] = []

    const result = await resumeCommand(engagement.id, {
      storeOverride: store,
      bridgeOverride: bridge,
      executorOverride: executorReturning({ status: "completed" }),
      onProgress: (event) => {
        if (typeof event === "string") progress.push(event)
      },
    })

    expect(progress.join("\n")).not.toContain("degraded step(s)")
    expect(result).not.toContain("## Degraded coverage")
    expect(store.getEngagement(engagement.id)!.status).toBe("COMPLETED")
  })
})
