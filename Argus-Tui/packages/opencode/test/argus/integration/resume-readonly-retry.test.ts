/**
 * A resumed read-only action is actually retried.
 *
 * `resume.ts` used to only write a "retrying" audit line; the executor was
 * never told to run the interrupted phase. This test mocks the bridge and
 * executor so it can prove the execution itself, not the audit prose.
 */
import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { tmpdir } from "os"
import { join } from "path"

const executed: string[] = []

import { EngagementStore } from "../../../src/argus/engagement/store"
import { buildCheckpoint } from "../../../src/argus/engagement/checkpoint"
import { scopeEntriesFor } from "../../../src/argus/browser/scope-guard"
import type { AssessmentPlan } from "../../../src/argus/planner/types"
import type { PhaseRecord } from "../../../src/argus/engagement/types"

let dbDir: string

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-resume-retry-"))
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
        name: "sqlmap",
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
    planCreatedAt: "2026-11-14T10:00:00.000Z",
  }
}

describe("resume retries interrupted read-only work", () => {
  test("the executor runs the interrupted phase, not just an audit line", async () => {
    const store = new EngagementStore(join(dbDir, "retry.db"))
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
        name: "sqlmap",
        status: "RUNNING",
        capabilities: [],
        executionMode: "sequential",
        replanCycle: true,
        startedAt: new Date(Date.parse(started) + 2000).toISOString(),
      },
    ]
    store.savePhases(engagement.id, phases)
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
          toolCalls: 1,
          requestCount: 1,
        },
        startedAt: started,
        now: new Date(Date.parse(started) + 3000),
      }),
    )

    // Simulate a stale phase write: the checkpoint (authoritative) says the
    // read-only action was in flight, while the phase row still claims it
    // finished. A retry that is only an audit line would trust the row and
    // skip the action; the resume path must trust the checkpoint and run it.
    store.savePhase(engagement.id, {
      ...phases[1],
      status: "COMPLETED",
      completedAt: new Date(Date.parse(started) + 2500).toISOString(),
    })

    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const result = await resumeCommand(engagement.id, {
      storeOverride: store,
      bridgeOverride: { connect: async () => {}, disconnect: async () => {} },
      executorOverride: {
        loadGates() {},
        setOnProgress() {},
        async execute(phase) {
          executed.push(phase.phaseId)
          return {
            phaseId: phase.phaseId,
            status: "completed" as const,
            findings: [],
            artifacts: [],
            errors: [],
            durationMs: 0,
          }
        },
      },
    })

    expect(executed).toEqual(["phase-scan"])
    expect(result).not.toContain("not safe to replay")
    const audit = store.getAuditLog(engagement.id)
    expect(
      audit.some(
        (entry) =>
          entry.eventType === "PHASE_RETRY_READ_ONLY" &&
          entry.message.includes("sqlmap"),
      ),
    ).toBe(true)
    expect(store.getEngagement(engagement.id)!.status).toBe("COMPLETED")
    const scan = store.getPhases(engagement.id).find((phase) => phase.id === "phase-scan")
    expect(scan?.status).toBe("COMPLETED")
  })
})
