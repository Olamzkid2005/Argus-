import { describe, expect, test, beforeAll, afterAll, afterEach, mock } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"

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

    mock.module("../../../../src/argus/engagement/store", () => ({
      EngagementStore: mock(() => store),
    }))

    mock.module("../../../../src/argus/engagement/credentials", () => ({
      CredentialStore: mock(() => ({
        load: mock(() => ({ roles: {} })),
        getAllCredentials: mock(() => ({
          attacker: { username: "attacker", password: "pass" },
          victim: { username: "victim", password: "pass" },
          user: { username: "user", password: "pass" },
          admin: { username: "admin", password: "pass" },
        })),
        clear: mock(() => {}),
      })),
    }))

    // NOTE: VerificationRunner is NOT mocked here to avoid contaminating
    // browser/verifiers/runner.test.ts across test files in bun.
    // Verification scenarios that go through the real VerificationRunner
    // will use the mocked PlaywrightEngine below.

    mock.module("../../../../src/argus/browser/engine", () => ({
      PlaywrightEngine: mock(() => ({
        launch: mock(async () => {}),
        createContext: mock(async () => {
          if (mockEvidenceCaptureThrow) throw new Error("engine context failed")
          return mockContext
        }),
        captureScreenshot: mock(async () => Buffer.from("screenshot-data")),
        close: mock(async () => {}),
      })),
    }))
  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  afterEach(() => {
    resetEngineMocks()
  })

  test("returns finding-not-found message for non-existent finding", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("find-nonexistent")
    expect(output).toContain("Finding not found")
    expect(output).toContain("find-nonexistent")
  })

  test("handles missing findingId gracefully", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(undefined as unknown as string)
    expect(typeof output).toBe("string")
  })

  test("never throws for arbitrary inputs", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("")
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
      status: "CONFIRMED",
      description: "Unknown vuln type",
      tool: "some-custom-tool",
      phase: "vuln_scan",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId)

    expect(output).toContain("No matching verifier found")
    expect(output).toContain("some-custom-tool")
    expect(output).toContain("Available roles")
  })

  test("uses targetUrl option when provided", async () => {
    const eng = store.createEngagement("https://custom-target.com", "assessment")
    const findingId = `find-target-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Test finding",
      severity: 3,
      confidence: 3,
      status: "CONFIRMED",
      description: "Test description",
      tool: "bola-scanner",
      phase: "vuln_scan",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, { targetUrl: "https://custom-target.com/api/resource/123" })

    expect(output).toContain("https://custom-target.com/api/resource/123")
  })

  test("includes finding id and tool info in output", async () => {
    const eng = store.createEngagement("https://info-test.com", "assessment")
    const findingId = `find-info-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Test Finding Title",
      severity: 3,
      confidence: 3,
      status: "CONFIRMED",
      description: "A description",
      tool: "bola-scanner",
      phase: "vuln_scan",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId)

    expect(output).toContain(findingId)
    expect(output).toContain("bola-scanner")
  })

  test("finds finding across multiple engagements", async () => {
    const eng1 = store.createEngagement("https://first.com", "assessment")
    store.saveFindings(eng1.id, [{
      id: "find-other-1",
      title: "First finding",
      severity: 2,
      confidence: 2,
      status: "CONFIRMED",
      description: "First",
      tool: "some-tool",
      phase: "recon",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const eng2 = store.createEngagement("https://second.com", "assessment")
    const findingId = `find-cross-eng-${Date.now()}`
    store.saveFindings(eng2.id, [{
      id: findingId,
      title: "Second finding",
      severity: 3,
      confidence: 3,
      status: "CONFIRMED",
      description: "Target",
      tool: "bola-scanner",
      phase: "vuln_scan",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId)

    expect(output).toContain(findingId)
    expect(output).toContain("bola-scanner")
  })
})
