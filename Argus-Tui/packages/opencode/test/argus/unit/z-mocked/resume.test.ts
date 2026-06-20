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

  test("resumeCommand returns success message for RUNNING engagement", async () => {
    const store = makeStore("happy-resume")
    const eng = store.createEngagement("https://test.com", "assessment")
    store.updateStatus(eng.id, "RUNNING")
    const { resumeCommand } = await import("../../../../src/argus/commands/resume")
    const result = await resumeCommand(eng.id, { storeOverride: store })
    expect(result).not.toContain("cannot be resumed")
    expect(result).not.toContain("Engagement not found")
  })
})
