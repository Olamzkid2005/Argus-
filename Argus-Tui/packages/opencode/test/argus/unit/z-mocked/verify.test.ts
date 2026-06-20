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
  goto: mock(async () => ({ status: () => 200 })),
  close: mock(async () => {}),
  content: mock(async () => "<html></html>"),
  url: mock(() => "https://example.com"),
  waitForLoadState: mock(async () => {}),
  locator: mock(() => ({
    innerText: mock(async () => "Dashboard"),
    count: mock(async () => 0),
    first: mock(() => ({
      isVisible: mock(async () => false),
      fill: mock(async () => {}),
      press: mock(async () => {}),
      click: mock(async () => {}),
    })),
  })),
}

const mockContext = {
  newPage: mock(async () => mockPage),
  close: mock(async () => {}),
}

const mockEngine = {
  launch: mock(async () => {}),
  createContext: mock(async () => mockContext),
  navigate: mock(async () => mockPage),
  observe: mock(async () => ({ url: "", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: new Date().toISOString() })),
  captureScreenshot: mock(async () => Buffer.from("mock")),
  close: mock(async () => {}),
}

const mockCredStore = {
  load: mock(() => ({ roles: {} })),
  getAllCredentials: mock(() => ({
    attacker: { username: "attacker", password: "pass" },
    victim: { username: "victim", password: "pass" },
  })),
  clear: mock(() => {}),
  getCredentials: mock(() => null),
  listRoles: mock(() => []),
  getDefaultRole: mock(() => undefined),
  getDefaultCredentials: mock(() => null),
  save: mock(() => {}),
}

const mockCollector = {
  captureScreenshot: mock(async () => ({
    path: "screenshots/test.png",
    hash: "abc123",
    type: "screenshot" as const,
    size_bytes: 100,
  })),
  createPackage: mock(async () => ({
    package_id: "test",
    engagement_id: "test",
    created_at: new Date().toISOString(),
    artifacts: [],
    package_hash: "",
  })),
}

const mockConfidence = {
  promote: mock((finding: any) => finding.confidence),
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
    store = makeStore(`verify-${Date.now()}`)
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

  test("passes engineOverride to verifier via VerificationRunner", async () => {
    const eng = store.createEngagement("https://bola-test.com", "assessment")
    const findingId = `find-bola-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "BOLA finding",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://bola-test.com/api/resource",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine,
      credStoreOverride: mockCredStore,
      collectorOverride: mockCollector,
      confidenceOverride: mockConfidence,
    })

    expect(output).toContain("BOLA")
    expect(output).toContain("confidence")
  })

  test("runs BOLA verification with mocked dependencies", async () => {
    const eng = store.createEngagement("https://bola-test.com", "assessment")
    const findingId = `find-bola-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "BOLA finding",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://bola-test.com/api/resource",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine,
      credStoreOverride: mockCredStore,
      collectorOverride: mockCollector,
      confidenceOverride: mockConfidence,
    })

    expect(output).toContain("BOLA")
    expect(output).toContain("confidence")
  })
})
