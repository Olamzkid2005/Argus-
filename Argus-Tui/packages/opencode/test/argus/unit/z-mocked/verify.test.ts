import { describe, expect, test, beforeAll, afterAll, afterEach, mock } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"
import type { PlaywrightEngine } from "../../../../src/argus/browser/engine"
import type { CredentialStore } from "../../../../src/argus/engagement/credentials"
import type { EvidenceCollector } from "../../../../src/argus/evidence/collector"
import type { ConfidenceEngine } from "../../../../src/argus/engagement/confidence"
import type { VerificationRunner } from "../../../../src/argus/browser/verifiers/runner"

let dbDir: string
let store: EngagementStore

function makeStore(name: string): EngagementStore {
  return new EngagementStore(join(dbDir, `${name}.db`))
}

let mockRunnerRunThrow = false
let mockEvidenceCaptureThrow = false

const mockPage = {
  goto: mock(async () => {}),
  close: mock(async () => {}),
  content: mock(async () => "<html></html>"),
  url: mock(() => "https://example.com"),
  waitForLoadState: mock(async () => {}),
}

const mockContext = {
  newPage: mock(async () => mockPage),
  close: mock(async () => {}),
}

function resetEngineMocks(): void {
  mockRunnerRunThrow = false
  mockEvidenceCaptureThrow = false
}

describe("verifyCommand", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-verify-test-"))
    store = makeStore("verify")
  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  afterEach(() => {
    resetEngineMocks()
  })

  test("returns finding-not-found message for non-existent finding", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("find-nonexistent", { storeOverride: store })
    expect(output).toContain("Finding not found")
    expect(output).toContain("find-nonexistent")
  })

  test("handles missing findingId gracefully", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(undefined as unknown as string, { storeOverride: store })
    expect(typeof output).toBe("string")
  })

  test("never throws for arbitrary inputs", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("", { storeOverride: store })
    expect(typeof output).toBe("string")
  })

  test("shows no matching verifier when finding tool does not match any verifier", async () => {
    const eng = store.createEngagement("https://unknown-test.com", "assessment")
    const findingId = `find-unknown-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Unknown finding",
      severity: 2,
      confidence: 2,
      status: "PENDING",
      description: "https://example.com/unknown",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, { storeOverride: store })

    expect(output).toContain("No matching verifier found")
  })

  test("uses targetUrl option when provided", async () => {
    const eng = store.createEngagement("https://target-test.com", "assessment")
    const findingId = `find-target-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Target test finding",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://custom-target.com",
    })

    expect(output).toContain("https://custom-target.com")
  })

  test("includes finding id and tool info in output", async () => {
    const eng = store.createEngagement("https://info-test.com", "assessment")
    const findingId = `find-info-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Info finding",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, { storeOverride: store })

    expect(output).toContain(findingId)
    expect(output).toContain("unknown-scanner")
  })

  test("finds finding across multiple engagements", async () => {
    store.createEngagement("https://other-eng.com", "assessment")
    const eng2 = store.createEngagement("https://target-eng.com", "assessment")
    const findingId = `find-multi-${Date.now()}`
    store.saveFindings(eng2.id, [{
      id: findingId,
      title: "Finding in second engagement",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "multi-test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, { storeOverride: store })

    expect(output).toContain(findingId)
    expect(output).toContain("unknown-scanner")
  })
})
