/**
 * A phase that is interrupted by a restart resumes with everything it already
 * collected, and the interrupted phase runs again instead of being skipped.
 *
 * Findings used to be written only after the last phase, so a restart mid-run
 * resumed against an empty database: the coverage of every completed phase was
 * gone and the next phase started from nothing. The fix writes findings at every
 * phase boundary, which is what this test exercises through a second store
 * instance over the same database file (a restart, not a reload).
 */
import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"

import { EngagementStore } from "../../../src/argus/engagement/store"
import { buildCheckpoint } from "../../../src/argus/engagement/checkpoint"
import { scopeEntriesFor } from "../../../src/argus/browser/scope-guard"
import type { AssessmentPlan } from "../../../src/argus/planner/types"
import type { PhaseRecord } from "../../../src/argus/engagement/types"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

let dbDir: string
const executed: string[] = []

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-restart-resume-"))
})

afterAll(() => {
  try {
    rmSync(dbDir, { recursive: true, force: true })
  } catch {}
})

function plan(): AssessmentPlan {
  return {
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
        toolExecution: "sequential",
        replanCycle: true,
      },
      {
        phaseId: "phase-scan",
        name: "vuln_scan",
        workflowName: "full_assessment",
        target: "https://example.com",
        requiredCapabilities: [],
        config: {},
        previousPhaseResults: [],
        toolExecution: "sequential",
        replanCycle: true,
      },
    ],
    errorRecovery: {},
    planCreatedAt: "2026-11-16T08:00:00.000Z",
  }
}

function finding(id: string, title: string, tool: string): NormalizedFinding {
  return {
    id,
    title,
    severity: 2,
    confidence: 2,
    status: "PENDING",
    description: `${title} observed on the target`,
    tool,
    phase: "recon",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}

describe("restart resumes with collected findings", () => {
  test("phase-boundary findings survive a restart and the interrupted phase completes", async () => {
    const dbPath = join(dbDir, "restart.db")
    const store = new EngagementStore(dbPath)
    const engagement = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(engagement.id, "INTERRUPTED")

    const started = new Date(Date.parse(engagement.createdAt) + 1000).toISOString()
    const phases: PhaseRecord[] = [
      {
        id: "phase-recon",
        engagementId: engagement.id,
        name: "recon",
        status: "COMPLETED",
        capabilities: [],
        executionMode: "sequential",
        replanCycle: true,
        startedAt: started,
        completedAt: new Date(Date.parse(started) + 1000).toISOString(),
      },
      {
        id: "phase-scan",
        engagementId: engagement.id,
        name: "vuln_scan",
        status: "RUNNING",
        capabilities: [],
        executionMode: "sequential",
        replanCycle: true,
        startedAt: new Date(Date.parse(started) + 2000).toISOString(),
      },
    ]
    store.savePhases(engagement.id, phases)

    // What the run had collected when the runner was killed: recon's findings,
    // written at the phase boundary rather than only at the end of the run.
    const reconFindings = [
      finding("find-recon-1", "Endpoint: /login.jsp", "katana"),
      finding("find-recon-2", "Open port: 80/tcp", "naabu"),
    ]
    store.saveFindings(engagement.id, reconFindings)

    store.saveCheckpoint(
      buildCheckpoint({
        engagement,
        plan: plan(),
        phases,
        scope: scopeEntriesFor(engagement.target),
        budgetUsage: {
          llmCalls: 1,
          llmFailures: 0,
          inputTokens: 1,
          outputTokens: 1,
          costUsd: 0,
          costKnown: true,
          toolCalls: 2,
          requestCount: 1,
        },
        startedAt: started,
        now: new Date(Date.parse(started) + 3000),
      }),
    )

    // A restart: a fresh process opens the same database file.
    const restarted = new EngagementStore(dbPath)
    expect(restarted.getFindings(engagement.id)).toHaveLength(2)

    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const message = await resumeCommand(engagement.id, {
      storeOverride: restarted,
      bridgeOverride: { connect: async () => {}, disconnect: async () => {} },
      executorOverride: {
        loadGates() {},
        setOnProgress() {},
        async execute(phase) {
          executed.push(phase.phaseId)
          return {
            phaseId: phase.phaseId,
            status: "completed" as const,
            findings: [{
              ...finding("find-scan-1", "SQL injection in id parameter", "sqlmap"),
              phase: phase.name,
            }],
            artifacts: [],
            errors: [],
            durationMs: 0,
          }
        },
      },
    })

    // The interrupted phase ran; the completed one did not.
    expect(executed).toEqual(["phase-scan"])
    expect(message).not.toContain("not found")

    const after = restarted.getFindings(engagement.id)
    expect(after).toHaveLength(3)
    expect(after.map((f) => f.title).sort()).toEqual([
      "Endpoint: /login.jsp",
      "Open port: 80/tcp",
      "SQL injection in id parameter",
    ])
    expect(after.every((f) => (f.tool ?? "").length > 0)).toBe(true)

    expect(restarted.getPhases(engagement.id).find((p) => p.id === "phase-scan")?.status).toBe("COMPLETED")
    expect(restarted.getEngagement(engagement.id)!.status).toBe("COMPLETED")
  })

  test("resuming twice does not duplicate what was already stored", () => {
    const store = new EngagementStore(join(dbDir, "idempotent.db"))
    const eng = store.createEngagement("https://example.com", "full_assessment")
    const records = [finding("find-a", "Endpoint: /a.jsp", "katana")]
    store.saveFindings(eng.id, records)
    store.saveFindings(eng.id, records)
    expect(store.getFindings(eng.id)).toHaveLength(1)
  })
})
