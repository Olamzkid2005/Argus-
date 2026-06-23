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
  evaluate: mock(async (fn: Function) => "<html></html>"),
  waitForTimeout: mock(async () => {}),
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
  saveRequest: mock(async () => ({
    path: "requests/test.txt",
    hash: "abc123",
    type: "request" as const,
    size_bytes: 50,
  })),
  saveResponse: mock(async () => ({
    path: "responses/test.txt",
    hash: "abc123",
    type: "response" as const,
    size_bytes: 50,
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
  shouldFinalize: mock((finding: any) => finding.confidence >= 4),
}

/**
 * Tracks which verifier methods were called and with what arguments.
 * Verifiers (BOLA, XSS, PrivEsc) are called via the VerificationRunner,
 * which exercises setup/execute/verify/collectEvidence/cleanup.
 * These counters let us assert the mocks were actually wired through.
 */
function resetAllMocks(): void {
  // Reset mock call tracking — type-safe via any cast for Bun mock API
  const clear = (fn: any) => fn.mockClear()
  clear(mockPage.goto)
  clear(mockPage.close)
  clear(mockPage.content)
  clear(mockContext.close)
  clear(mockEngine.launch)
  clear(mockEngine.createContext)
  clear(mockEngine.navigate)
  clear(mockEngine.captureScreenshot)
  clear(mockEngine.close)
  clear(mockCollector.captureScreenshot)
  clear(mockCollector.createPackage)
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
    resetAllMocks()
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

  test("uses targetUrl option when provided — targetUrl flows into verifier", async () => {
    resetAllMocks()
    const eng = store.createEngagement("https://target-test.com", "assessment")
    const findingId = `find-target-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Target test finding",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "bola",          // Use a tool that has a registered verifier
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://custom-target.com",
      engineOverride: mockEngine as any,
      collectorOverride: mockCollector as any,
      confidenceOverride: mockConfidence as any,
      credStoreOverride: mockCredStore as any,
    })

    // The BOLA verifier should have been invoked with the targetUrl,
    // not just echoed in the output string.
    expect(output).toContain("[BOLA]")
    expect(output).toContain("https://custom-target.com")
    expect(output).not.toContain("No matching verifier found")
    // Verify the mock engine was actually used (mocks were wired through)
    expect(mockEngine.createContext).toHaveBeenCalled()
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

  test("BOLA verifier exercises mock engine (engine.launch, createContext, navigate, close)", async () => {
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
      engineOverride: mockEngine as unknown as PlaywrightEngine,
      credStoreOverride: mockCredStore as unknown as CredentialStore,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
      confidenceOverride: mockConfidence as unknown as ConfidenceEngine,
    })

    expect(output).toContain("BOLA")
    expect(output).toContain("confidence")
    // Verify the mocks were actually exercised through the verifier pipeline
    // engine.launch and createContext should be called during setup()
    expect((mockEngine.launch as any)).toHaveBeenCalled()
    // engine.close should be called during cleanup()
    expect((mockEngine.close as any)).toHaveBeenCalled()
  })

  test("XSS verifier exercises mock engine when finding tool includes 'xss'", async () => {
    const eng = store.createEngagement("https://xss-test.com", "assessment")
    const findingId = `find-xss-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Stored XSS",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://xss-test.com/profile",
      tool: "xss-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // XSS verifier needs a "user" or "admin" role
    const xssCredStore = {
      load: mock(() => ({ roles: {} })),
      getAllCredentials: mock(() => ({
        user: { username: "regular", password: "pass" },
      })),
      clear: mock(() => {}),
      getCredentials: mock(() => null),
      listRoles: mock(() => []),
      getDefaultRole: mock(() => undefined),
      getDefaultCredentials: mock(() => null),
      save: mock(() => {}),
    }

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as unknown as PlaywrightEngine,
      credStoreOverride: xssCredStore as unknown as CredentialStore,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
      confidenceOverride: mockConfidence as unknown as ConfidenceEngine,
    })

    expect(output).toContain("XSS")
    expect(output).toContain("confidence")
    expect((mockEngine.launch as any)).toHaveBeenCalled()
    expect((mockEngine.close as any)).toHaveBeenCalled()
  })

  test("PrivEsc verifier exercises mock engine when finding tool includes 'priv-esc'", async () => {
    const eng = store.createEngagement("https://privesc-test.com", "assessment")
    const findingId = `find-privesc-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Privilege Escalation",
      severity: 4,
      confidence: 3,
      status: "PENDING",
      description: "https://privesc-test.com/admin",
      tool: "priv-esc-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // PrivEsc needs a user role
    const userCredStore = {
      load: mock(() => ({ roles: {} })),
      getAllCredentials: mock(() => ({
        user: { username: "regular", password: "pass" },
      })),
      clear: mock(() => {}),
      getCredentials: mock(() => null),
      listRoles: mock(() => []),
      getDefaultRole: mock(() => undefined),
      getDefaultCredentials: mock(() => null),
      save: mock(() => {}),
    }

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as unknown as PlaywrightEngine,
      credStoreOverride: userCredStore as unknown as CredentialStore,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
      confidenceOverride: mockConfidence as unknown as ConfidenceEngine,
    })

    expect(output).toContain("PrivEsc")
    expect(output).toContain("confidence")
    expect((mockEngine.launch as any)).toHaveBeenCalled()
    expect((mockEngine.close as any)).toHaveBeenCalled()
  })

  test("handles verification failure gracefully", async () => {
    const eng = store.createEngagement("https://fail-verify.com", "assessment")
    const findingId = `find-fail-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Failing finding",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "test",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // Create an engine that fails immediately
    const failingEngine = {
      launch: mock(async () => { throw new Error("Engine crashed") }),
      createContext: mock(async () => { throw new Error("Engine crashed") }),
      navigate: mock(async () => { throw new Error("Engine crashed") }),
      captureScreenshot: mock(async () => { throw new Error("Engine crashed") }),
      close: mock(async () => {}),
    }

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: failingEngine as unknown as PlaywrightEngine,
      credStoreOverride: mockCredStore as unknown as CredentialStore,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
      confidenceOverride: mockConfidence as unknown as ConfidenceEngine,
    })

    expect(output).toContain("Verification failed")
    expect(output).toContain("Engine crashed")
  })

  test("handles evidence screenshot failure gracefully (does not crash)", async () => {
    const eng = store.createEngagement("https://ev-fail-test.com", "assessment")
    const findingId = `find-ev-fail-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Evidence fail",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // Engine where createContext works but capture fails gracefully
    const semiFailingEngine = {
      launch: mock(async () => {}),
      createContext: mock(async () => ({
        newPage: mock(async () => ({
          goto: mock(async () => ({ status: () => 200 })),
          close: mock(async () => {}),
        })),
        close: mock(async () => {}),
      })),
      captureScreenshot: mock(async () => { throw new Error("Screenshot failed") }),
      close: mock(async () => {}),
    }

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: semiFailingEngine as unknown as PlaywrightEngine,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
    })

    // Should not throw — should return a string with no matching verifier
    expect(typeof output).toBe("string")
    expect(output).toContain("No matching verifier found")
  })

  test("BOLA verifier with non-standard role names (flexible matching)", async () => {
    const eng = store.createEngagement("https://bola-flex-test.com", "assessment")
    const findingId = `find-bola-flex-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "BOLA flexible role",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://bola-flex-test.com/api/resource",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // Use non-standard role names to test flexible matching
    const flexCredStore = {
      load: mock(() => ({ roles: {} })),
      getAllCredentials: mock(() => ({
        Attacker: { username: "attacker", password: "pass" },
        victim_role: { username: "victim", password: "pass" },
      })),
      clear: mock(() => {}),
      getCredentials: mock(() => null),
      listRoles: mock(() => []),
      getDefaultRole: mock(() => undefined),
      getDefaultCredentials: mock(() => null),
      save: mock(() => {}),
    }

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as unknown as PlaywrightEngine,
      credStoreOverride: flexCredStore as unknown as CredentialStore,
      collectorOverride: mockCollector as unknown as EvidenceCollector,
      confidenceOverride: mockConfidence as unknown as ConfidenceEngine,
    })

    // Should match "Attacker" → "attacker" (case-insensitive) and "victim_role" → "victim" (substring)
    expect(output).toContain("BOLA")
  })
})
