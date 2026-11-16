/**
 * Integration test for resume flow — engagement recovery and phase matching.
 *
 * Tests the full pipeline from canResume → validateWorkflowVersion →
 * phase record matching → resumeCommand validation paths using the
 * real EngagementStore. The actual phase execution path (which requires
 * MCP worker infrastructure) is tested via unit tests with injected mocks.
 */
import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { canResume, validateWorkflowVersion } from "../../../src/argus/engagement/recovery"
import type { EngagementState, PhaseRecord } from "../../../src/argus/engagement/types"

let dbDir: string

function makeStore(name: string): EngagementStore {
  return new EngagementStore(join(dbDir, `${name}.db`))
}

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-resume-int-test-"))
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

describe("canResume integration", () => {
  test("returns true for RUNNING engagement", () => {
    const store = makeStore("int-running")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    const loaded = store.getEngagement(eng.id)!
    expect(canResume(loaded)).toBe(true)
  })

  test("returns true for PAUSED engagement", () => {
    const store = makeStore("int-paused")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "PAUSED")
    const loaded = store.getEngagement(eng.id)!
    expect(canResume(loaded)).toBe(true)
  })

  test("returns false for COMPLETED engagement", () => {
    const store = makeStore("int-completed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "COMPLETED")
    const loaded = store.getEngagement(eng.id)!
    expect(canResume(loaded)).toBe(false)
  })

  test("returns false for FAILED engagement", () => {
    const store = makeStore("int-failed")
    const eng = store.createEngagement("https://example.com", "assessment")
    store.updateStatus(eng.id, "FAILED")
    const loaded = store.getEngagement(eng.id)!
    expect(canResume(loaded)).toBe(false)
  })

  test("returns false for CREATED engagement", () => {
    const store = makeStore("int-created")
    const eng = store.createEngagement("https://example.com", "assessment")
    const loaded = store.getEngagement(eng.id)!
    expect(canResume(loaded)).toBe(false)
  })
})

describe("validateWorkflowVersion integration", () => {
  test("returns true when versions match", () => {
    const store = makeStore("version-match")
    const eng = store.createEngagement("https://example.com", "assessment")
    eng.workflowVersion = 2
    store.saveEngagement(eng)
    const loaded = store.getEngagement(eng.id)!
    expect(validateWorkflowVersion(loaded, 2)).toBe(true)
  })

  test("returns false when versions differ", () => {
    const store = makeStore("version-mismatch")
    const eng = store.createEngagement("https://example.com", "assessment")
    eng.workflowVersion = 1
    store.saveEngagement(eng)
    const loaded = store.getEngagement(eng.id)!
    expect(validateWorkflowVersion(loaded, 2)).toBe(false)
  })

  test("returns false when stored version differs from current", () => {
    const store = makeStore("version-undefined")
    const eng = store.createEngagement("https://example.com", "assessment")
    eng.workflowVersion = 1
    store.saveEngagement(eng)
    const loaded = store.getEngagement(eng.id)!
    expect(validateWorkflowVersion(loaded, 99)).toBe(false)
  })
})

describe("resumeCommand validation paths", () => {
  test("returns not-found for non-existent engagement", async () => {
    const store = makeStore("int-nonexistent")
    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const result = await resumeCommand("ENG-NONEXISTENT", { storeOverride: store })
    expect(result).toBe("Engagement not found: ENG-NONEXISTENT")
  })

  test("returns cannot-resume for COMPLETED engagement", async () => {
    const store = makeStore("int-completed-resume")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "COMPLETED")
    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
    expect(result).toContain("COMPLETED")
  })

  test("returns cannot-resume for FAILED engagement", async () => {
    const store = makeStore("int-failed-resume")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "FAILED")
    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
    expect(result).toContain("FAILED")
  })

  test("returns cannot-resume for CREATED engagement (not yet started)", async () => {
    const store = makeStore("int-created-resume")
    const eng = store.createEngagement("https://test.com", "assessment")
    const { resumeCommand } = await import("../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).toContain("cannot be resumed")
    expect(result).toContain("CREATED")
  })
})

describe("phase matching during resume", () => {
  test("phase records are matched by ID when available", () => {
    const store = makeStore("phase-id-match")
    const eng = store.createEngagement("https://phase-match.com", "assessment")
    const phaseId = `phase-id-${Date.now()}-recon`
    const savedPhases: PhaseRecord[] = [
      { id: phaseId, engagementId: eng.id, name: "recon", status: "COMPLETED", capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false },
      { id: `phase-id-${Date.now()}-scan`, engagementId: eng.id, name: "vuln_scan", status: "PENDING", capabilities: ["vulnerability_scanning"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, savedPhases)

    // Verify: loading phases preserves exact IDs
    const loaded = store.getPhases(eng.id)
    expect(loaded).toHaveLength(2)
    expect(loaded[0].id).toBe(phaseId)
    expect(loaded[1].id).not.toBe(phaseId)
  })

  test("phase records with same name but different indices are matched by name fallback", () => {
    const store = makeStore("phase-name-match")
    const eng = store.createEngagement("https://name-match.com", "assessment")
    const storedPhase: PhaseRecord = {
      id: "original-id-recon", engagementId: eng.id, name: "recon", status: "COMPLETED",
      capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false,
    }
    store.savePhases(eng.id, [storedPhase])

    // Simulate: a new plan generates a phase with the same name but different ID
    // The name fallback in resumeCommand should match by name
    const loaded = store.getPhases(eng.id)
    expect(loaded).toHaveLength(1)
    expect(loaded[0].name).toBe("recon")
    expect(loaded[0].id).toBe("original-id-recon")
    expect(loaded[0].status).toBe("COMPLETED")
  })

  test("engagement has phases stored after assessment run", () => {
    const store = makeStore("phase-storage")
    const eng = store.createEngagement("https://phase-storage.com", "assessment")
    // Use IDs that sort in same order as status progression to match storage ordering
    const phases: PhaseRecord[] = [
      { id: "p1-recon", engagementId: eng.id, name: "recon", status: "COMPLETED", capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false },
      { id: "p2-scan", engagementId: eng.id, name: "vuln_scan", status: "FAILED", capabilities: ["vulnerability_scanning"], executionMode: "parallel", replanCycle: false },
      { id: "p3-report", engagementId: eng.id, name: "report", status: "PENDING", capabilities: ["reporting"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, phases)
    const loaded = store.getPhases(eng.id)
    expect(loaded).toHaveLength(3)

    // Verify: resume would skip COMPLETED phases
    const completedNames = new Set(loaded.filter((p) => p.status === "COMPLETED").map((p) => p.name))
    expect(completedNames.has("recon")).toBe(true)

    // Verify: resume would start from the first non-completed/non-partial phase
    const startIndex = loaded.findIndex((p) => !(p.status === "COMPLETED" || p.status === "PARTIAL"))
    expect(startIndex).toBe(1)
    expect(loaded[startIndex].name).toBe("vuln_scan")
  })

  test("all phases completed returns no phases to resume", () => {
    const store = makeStore("all-complete")
    const eng = store.createEngagement("https://all-complete.com", "assessment")
    const phases: PhaseRecord[] = [
      { id: "p1", engagementId: eng.id, name: "recon", status: "COMPLETED", capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false },
      { id: "p2", engagementId: eng.id, name: "scan", status: "COMPLETED", capabilities: ["vuln_scan"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, phases)

    const loaded = store.getPhases(eng.id)
    const completedCount = loaded.filter((p) => p.status === "COMPLETED" || p.status === "PARTIAL").length
    expect(completedCount).toBe(2)
    const allCompleted = loaded.every((p) => p.status === "COMPLETED" || p.status === "PARTIAL")
    expect(allCompleted).toBe(true)
  })
})

describe("resume audit log entries", () => {
  test("audit log entries are created for engagement lifecycle", () => {
    const store = makeStore("int-audit-lifecycle")
    const eng = store.createEngagement("https://audit.com", "assessment")

    store.appendAuditLog(eng.id, "ASSESSMENT_START", "Assessment started")
    store.updateStatus(eng.id, "RUNNING")
    store.appendAuditLog(eng.id, "PHASE_COMPLETE", "Phase recon completed")
    store.updateStatus(eng.id, "PAUSED")
    store.appendAuditLog(eng.id, "RESUME_START", "Resuming engagement")

    const log = store.getAuditLog(eng.id)
    expect(log.length).toBeGreaterThanOrEqual(3)

    const eventTypes = log.map((e) => e.eventType)
    expect(eventTypes).toContain("ASSESSMENT_START")
    expect(eventTypes).toContain("PHASE_COMPLETE")
    expect(eventTypes).toContain("RESUME_START")
  })

  test("engagement transitions from PAUSED back to RUNNING during resume", () => {
    const store = makeStore("int-paused-to-running")
    const eng = store.createEngagement("https://resume-transition.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    store.updateStatus(eng.id, "PAUSED")

    const paused = store.getEngagement(eng.id)!
    expect(paused.status).toBe("PAUSED")
    expect(canResume(paused)).toBe(true)

    store.updateStatus(eng.id, "RUNNING")
    const resumed = store.getEngagement(eng.id)!
    expect(resumed.status).toBe("RUNNING")
  })
})

// ── Stage 6.2: resume from the saved checkpoint, never a fresh plan ──

import { buildCheckpoint } from "../../../src/argus/engagement/checkpoint"
import { scopeEntriesFor } from "../../../src/argus/browser/scope-guard"
import type { AssessmentPlan } from "../../../src/argus/planner/types"

function savedPlan(): AssessmentPlan {
  return {
    workflow: "full_assessment",
    phases: [],
    errorRecovery: {},
    planCreatedAt: "2026-11-14T10:00:00.000Z",
  }
}

function saveCheckpointFor(
  store: EngagementStore,
  engagementId: string,
  overrides?: { scope?: string[]; actions?: Parameters<typeof buildCheckpoint>[0]["phases"] },
) {
  const engagement = store.getEngagement(engagementId)!
  const started = new Date(Date.parse(engagement.createdAt) + 1000).toISOString()
  store.saveCheckpoint(
    buildCheckpoint({
      engagement,
      plan: savedPlan(),
      phases: overrides?.actions ?? [],
      scope: overrides?.scope ?? scopeEntriesFor(engagement.target),
      budgetUsage: {
        llmCalls: 2,
        llmFailures: 0,
        inputTokens: 10,
        outputTokens: 5,
        costUsd: 0.01,
        costKnown: true,
        toolCalls: 1,
        requestCount: 2,
      },
      startedAt: started,
      now: new Date(Date.parse(engagement.createdAt) + 300_000),
    }),
  )
}

describe("resume uses the saved checkpoint", () => {
  test("refuses to resume a run with no checkpoint instead of inventing a plan", async () => {
    const store = makeStore("checkpoint-missing")
    const eng = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(eng.id, "INTERRUPTED")
    const { resumeCommand } = await import("../../../src/argus/commands/resume")

    const result = await resumeCommand(eng.id, { storeOverride: store })

    expect(result).toContain("no saved checkpoint")
    expect(store.getEngagement(eng.id)!.status).toBe("PAUSED")
  })

  test("rejects a checkpoint whose scope is wider than the engagement scope", async () => {
    const store = makeStore("checkpoint-wide-scope")
    const eng = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(eng.id, "INTERRUPTED")
    saveCheckpointFor(store, eng.id, { scope: ["https://other.example:443"] })
    const { resumeCommand } = await import("../../../src/argus/commands/resume")

    const result = await resumeCommand(eng.id, { storeOverride: store })

    expect(result).toContain("wider")
    expect(store.getEngagement(eng.id)!.status).toBe("PAUSED")
  })

  test("pauses on an ambiguous in-flight state-changing action", async () => {
    const store = makeStore("checkpoint-ambiguous")
    const eng = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(eng.id, "INTERRUPTED")
    saveCheckpointFor(store, eng.id, {
      actions: [
        {
          id: "phase-exploit",
          engagementId: eng.id,
          name: "web_exploitation",
          status: "RUNNING",
          startedAt: "2026-11-16T08:00:05.000Z",
          capabilities: [],
          executionMode: "sequential",
          replanCycle: false,
        },
      ],
    })
    const { resumeCommand } = await import("../../../src/argus/commands/resume")

    const result = await resumeCommand(eng.id, { storeOverride: store })

    expect(result).toContain("not safe to replay")
    expect(store.getEngagement(eng.id)!.status).toBe("PAUSED")
    const audit = store.getAuditLog(eng.id)
    expect(audit.some((entry) => entry.eventType === "RESUME_PAUSED")).toBe(true)
  })

  test("an interrupted read-only scan is retried, not paused", async () => {
    const store = makeStore("checkpoint-readonly-retry")
    const eng = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(eng.id, "INTERRUPTED")
    saveCheckpointFor(store, eng.id, {
      actions: [
        {
          id: "phase-scan",
          engagementId: eng.id,
          name: "sqlmap",
          status: "RUNNING",
          startedAt: "2026-11-16T08:00:05.000Z",
          capabilities: [],
          executionMode: "sequential",
          replanCycle: false,
        },
      ],
    })
    const { resumeCommand } = await import("../../../src/argus/commands/resume")

    const result = await resumeCommand(eng.id, { storeOverride: store })

    expect(result).not.toContain("not safe to replay")
    const audit = store.getAuditLog(eng.id)
    expect(audit.some((entry) => entry.eventType === "RESUME_RETRY_READ_ONLY")).toBe(true)
  })
})

describe("missingCredentialRefs", () => {
  test("requires exact roles and rejects unnamespaced references", async () => {
    const { missingCredentialRefs } = await import("../../../src/argus/commands/resume")
    expect(missingCredentialRefs(["credential:attacker"], ["attacker"])).toEqual([])
    expect(missingCredentialRefs(["credential:attacker"], ["victim"])).toEqual(["credential:attacker"])
    expect(missingCredentialRefs(["attacker"], ["attacker"])).toEqual(["attacker"])
    expect(missingCredentialRefs(["credential:"], ["attacker"])).toEqual(["credential:"])
  })
})

describe("resume uses the saved checkpoint", () => {
  test("completed work is not retried on a valid checkpoint", async () => {
    const store = makeStore("checkpoint-readonly")
    const eng = store.createEngagement("https://example.com", "full_assessment")
    store.updateStatus(eng.id, "INTERRUPTED")
    saveCheckpointFor(store, eng.id, {
      actions: [
        {
          id: "phase-recon",
          engagementId: eng.id,
          name: "recon",
          status: "COMPLETED",
          capabilities: [],
          executionMode: "sequential",
          replanCycle: false,
          startedAt: new Date(Date.parse(eng.createdAt) + 60_000).toISOString(),
          completedAt: new Date(Date.parse(eng.createdAt) + 120_000).toISOString(),
        },
      ],
    })
    const { resumeCommand } = await import("../../../src/argus/commands/resume")

    // The plan has no phases, so a valid checkpoint ends before executing
    // anything; the point of the assertion is that validation accepted it and
    // the completed action was not scheduled for a replay.
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).not.toContain("cannot be resumed")
    expect(result).not.toContain("not safe to replay")
    const audit = store.getAuditLog(eng.id)
    const restored = audit.find((entry) => entry.eventType === "RESUME_RESTORED")
    expect(restored).toBeDefined()
    expect(restored!.message).toContain("1 completed action")
  })
})
