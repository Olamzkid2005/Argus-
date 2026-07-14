/**
 * Integration test for verifyCommand — end-to-end verification pipeline.
 *
 * Tests the full flow from finding lookup → role matching → verifier
 * selection → execution → evidence capture using injected mock
 * dependencies. This verifies that all the pieces (EngagementStore,
 * CredentialStore, verifier selection logic, evidence capture) work
 * together correctly without actually launching a browser.
 */
import { describe, expect, test, beforeAll, afterAll, afterEach, mock } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { PlaywrightEngine } from "../../../src/argus/browser/engine"
import type { CredentialStore } from "../../../src/argus/engagement/credentials"
import type { EvidenceCollector } from "../../../src/argus/evidence/collector"
import type { ConfidenceEngine } from "../../../src/argus/engagement/confidence"

let dbDir: string
let store: EngagementStore

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
  setExtraHTTPHeaders: mock(async () => {}),
}

const mockEngine: any = {
  launch: mock(async () => {}),
  createContext: mock(async () => mockContext),
  navigate: mock(async () => mockPage),
  observe: mock(async () => ({ url: "", domSnapshot: "", responseHeaders: {}, statusCode: 200, timestamp: new Date().toISOString() })),
  captureScreenshot: mock(async () => Buffer.from("mock-screenshot")),
  close: mock(async () => {}),
}

const mockCredStore: any = {
  load: mock(() => ({ roles: {} })),
  getAllCredentials: mock(() => ({
    attacker: { username: "attacker", password: "pass" },
    victim: { username: "victim", password: "pass" },
    user: { username: "regular", password: "pass" },
    admin: { username: "admin", password: "admin123" },
  })),
  clear: mock(() => {}),
  getCredentials: mock(() => null),
  listRoles: mock(() => []),
  getDefaultRole: mock(() => undefined),
  getDefaultCredentials: mock(() => null),
  save: mock(() => {}),
}

const mockCollector: any = {
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
    package_id: "pkg-1",
    engagement_id: "eng-1",
    created_at: new Date().toISOString(),
    artifacts: [],
    package_hash: "abc",
  })),
  pruneEngagement: mock(async () => 0),
  checkStorageLimit: mock(async () => true),
}

const mockConfidence: any = {
  promote: mock((finding: any) => finding.confidence),
  shouldFinalize: mock((finding: any) => finding.confidence >= 4),
}

describe("verifyCommand full-pipeline integration", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-verify-int-test-"))
    store = new EngagementStore(join(dbDir, "verify-int.db"))
  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  test("returns finding-not-found for non-existent finding", async () => {
    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand("find-nonexistent", { storeOverride: store })
    expect(output).toContain("Finding not found")
    expect(output).toContain("find-nonexistent")
  })

  test("finds finding across multiple engagements", async () => {
    store.createEngagement("https://eng-1.com", "assessment")
    const eng2 = store.createEngagement("https://eng-2.com", "assessment")
    const findingId = `find-multi-${Date.now()}`
    store.saveFindings(eng2.id, [{
      id: findingId,
      title: "Multi-engagement finding",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "test",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    expect(output).toContain(findingId)
    expect(output).toContain("bola-scanner")
  })

  test("BOLA verifier is selected when tool contains 'bola'", async () => {
    const eng = store.createEngagement("https://bola-target.com", "assessment")
    const findingId = `find-bola-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "BOLA test",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://bola-target.com/api/resource",
      tool: "bola-detector",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    expect(output).toContain("BOLA")
    expect(output).toContain("confidence")
    expect((mockEngine.launch as any)).toHaveBeenCalled()
    expect((mockEngine.close as any)).toHaveBeenCalled()
  })

  test("XSS verifier is selected when tool contains 'xss' and user role exists", async () => {
    const eng = store.createEngagement("https://xss-target.com", "assessment")
    const findingId = `find-xss-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Stored XSS",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "https://xss-target.com/profile",
      tool: "xss-detector",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    expect(output).toContain("XSS")
    expect(output).toContain("confidence")
  })

  test("PrivEsc verifier is selected when tool contains 'priv-esc' and user role exists", async () => {
    const eng = store.createEngagement("https://privesc-target.com", "assessment")
    const findingId = `find-privesc-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Privilege Escalation",
      severity: 4,
      confidence: 3,
      status: "PENDING",
      description: "https://privesc-target.com/admin",
      tool: "priv-esc-detector",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    expect(output).toContain("PrivEsc")
    expect(output).toContain("confidence")
  })

  test("uses targetUrl option when provided", async () => {
    const eng = store.createEngagement("https://default-target.com", "assessment")
    const findingId = `find-target-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Target test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://custom-target.com",
      engineOverride: mockEngine as PlaywrightEngine,
      collectorOverride: mockCollector as EvidenceCollector,
    })

    expect(output).toContain("https://custom-target.com")
  })

  test("reports 'No matching verifier' for unknown tool types", async () => {
    const eng = store.createEngagement("https://unknown-tool.com", "assessment")
    const findingId = `find-unknown-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Unknown finding",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "custom-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
    })

    expect(output).toContain("No matching verifier found")
    expect(output).toContain("custom-scanner")
  })

  test("evidence is captured after verification", async () => {
    const eng = store.createEngagement("https://evidence-target.com", "assessment")
    const findingId = `find-evidence-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Evidence test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "unknown-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      collectorOverride: mockCollector as EvidenceCollector,
    })

    expect(output).toContain("Evidence captured")
    expect(output).toContain(findingId)
  })

  test("handles engine crash gracefully during verification", async () => {
    const eng = store.createEngagement("https://crash-target.com", "assessment")
    const findingId = `find-crash-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Crash test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const crashingEngine = {
      launch: mock(async () => { throw new Error("Browser launch failed") }),
      createContext: mock(async () => { throw new Error("Browser launch failed") }),
      navigate: mock(async () => { throw new Error("Browser launch failed") }),
      captureScreenshot: mock(async () => { throw new Error("Browser launch failed") }),
      close: mock(async () => {}),
    }

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: crashingEngine as unknown as PlaywrightEngine,
      credStoreOverride: mockCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    // Should not throw — should return error message
    expect(typeof output).toBe("string")
    expect(output).toContain("Verification failed")
    expect(output).toContain("Browser launch failed")
  })

  test("flexible role matching works with non-standard role names", async () => {
    const eng = store.createEngagement("https://flex-role.com", "assessment")
    const findingId = `find-flex-int-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Flexible role test",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "test",
      tool: "bola-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const flexCredStore: Partial<CredentialStore> = {
      load: mock(() => ({ roles: {} })),
      getAllCredentials: mock(() => ({
        Attacker: { username: "attacker_user", password: "pass" },
        Victim_Role: { username: "victim_user", password: "pass" },
      })),
      clear: mock(() => {}),
      getCredentials: mock(() => null),
      listRoles: mock(() => []),
      getDefaultRole: mock(() => undefined),
      getDefaultCredentials: mock(() => null),
      save: mock(() => {}),
    }

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      engineOverride: mockEngine as PlaywrightEngine,
      credStoreOverride: flexCredStore as CredentialStore,
      collectorOverride: mockCollector as EvidenceCollector,
      confidenceOverride: mockConfidence as ConfidenceEngine,
    })

    // Should match "Attacker" → "attacker" (case-insensitive) and "Victim_Role" → "victim" (substring)
    expect(output).toContain("BOLA")
  })
})
