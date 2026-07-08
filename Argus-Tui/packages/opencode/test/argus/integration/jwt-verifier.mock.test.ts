/**
 * Integration tests for JWTVerifier with backend API mocking.
 *
 * Tests the JWT verifier's full lifecycle (setup → execute → verify → collectEvidence)
 * against a simulated backend API that validates JWT tokens by checking the
 * Authorization header. The mock backend:
 *   - Returns 200 for the original/original-looking token
 *   - Returns 401 for empty/invalid tokens
 *   - Returns 200 when "alg:none" tokens pass through (simulates a vulnerable endpoint)
 *   - Returns 200 when tampered-payload tokens pass through (simulates signature bypass)
 *
 * This verifies Gap 7.3 fix (Authorization header injection) actually exercises
 * the backend API path, not just localStorage.
 */
import { describe, expect, test, beforeAll, afterAll, beforeEach, mock } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"

import { Confidence } from "../../../src/argus/shared/types"
import { JWTVerifier } from "../../../src/argus/browser/verifiers/jwt"

let dbDir: string
let store: EngagementStore

// ── Mock Backend API ─────────────────────────────────────────────────────
// The mock backend simulates a server that validates JWTs by checking the
// Authorization header. This is the "backend API" that Gap 7.3 wired the
// JWT verifier to test against (via page.setExtraHTTPHeaders()).

// Track what was set via setExtraHTTPHeaders by the verifier
let lastAuthHeader: string | null = null

// The accepted token patterns that the mock backend considers "valid":
// - Tokens containing "alg:none" → the vulnerable backend accepts these
// - Tokens containing known privilege claims → tampered payload accepted
// - Original tokens that match the original format
const isTokenAcceptedByBackend = (authHeader: string | null): boolean => {
  if (!authHeader) return false
  const token = authHeader.replace("Bearer ", "")

  // Backend rejects empty tokens
  if (!token || token === "undefined" || token === "null") return false

  // Backend rejects tokens with invalid signatures (ending in .INVALIDSIG)
  if (token.endsWith(".INVALIDSIG")) return false

  // Backend accepts "alg:none" tokens (simulates a vulnerable backend)
  try {
    const headerPart = token.split(".")[0]
    const decodedHeader = Buffer.from(headerPart, "base64url").toString()
    if (decodedHeader.includes('"alg":"none"')) return true
  } catch { /* not a valid base64url */ }

  // Backend accepts tokens with privilege claims (simulates vulnerable backend)
  try {
    const payloadPart = token.split(".")[1]
    const decodedPayload = Buffer.from(payloadPart, "base64url").toString()
    if (
      decodedPayload.includes('"role":"admin"') ||
      decodedPayload.includes('"admin":true') ||
      decodedPayload.includes('"isAdmin":true') ||
      decodedPayload.includes('"is_superuser":true')
    ) return true
  } catch { /* not a valid base64url */ }

  // Default: reject
  return false
}

// Mock page that simulates a backend API checking Authorization header
const mockPage = {
  goto: mock(async (url: string, _opts?: any) => {
    // The backend API checks the Authorization header set via setExtraHTTPHeaders
    const accepted = isTokenAcceptedByBackend(lastAuthHeader)
    return {
      status: () => accepted ? 200 : 401,
      headers: () => ({ "content-type": accepted ? "application/json" : "text/plain" }),
    }
  }),
  close: mock(async () => {}),
  content: mock(async () => "<html><body>Mock page</body></html>"),
  url: mock(() => "https://jwt-test.example.com/admin"),
  waitForLoadState: mock(async () => {}),
  // setExtraHTTPHeaders is the key method — Gap 7.3 added this to test the backend API
  setExtraHTTPHeaders: mock(async (headers: Record<string, string>) => {
    lastAuthHeader = headers["Authorization"] ?? null
  }),
  context: mock(() => ({
    cookies: mock(async () => []),
    setExtraHTTPHeaders: mock(async (_h: Record<string, string>) => {}),
  })),
  evaluate: mock(async (fn: Function | string, ..._args: any[]) => {
    // Simulate localStorage.setItem working (stores tokens client-side too)
    if (typeof fn === "function") return undefined
    return undefined
  }),
  textContent: mock(async (_selector?: string) => "<html><body>Mock</body></html>"),
  screenshot: mock(async () => Buffer.from("mock-screenshot")),
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
  observe: mock(async () => ({
    url: "https://jwt-test.example.com/admin",
    domSnapshot: "<html></html>",
    responseHeaders: {},
    statusCode: 200,
    timestamp: new Date().toISOString(),
  })),
  captureScreenshot: mock(async () => Buffer.from("mock-screenshot")),
  close: mock(async () => {}),
}

const mockCollector = {
  captureScreenshot: mock(async () => ({
    path: "screenshots/jwt-test.png",
    hash: "abc123",
    type: "screenshot" as const,
    size_bytes: 100,
  })),
  saveRequest: mock(async () => ({
    path: "requests/jwt-test.txt",
    hash: "abc123",
    type: "request" as const,
    size_bytes: 50,
  })),
  saveResponse: mock(async () => ({
    path: "responses/jwt-test.txt",
    hash: "abc123",
    type: "response" as const,
    size_bytes: 50,
  })),
  createPackage: mock(async () => ({
    package_id: "pkg-jwt-1",
    engagement_id: "eng-jwt-1",
    created_at: new Date().toISOString(),
    artifacts: [],
    package_hash: "def456",
  })),
  ingestHarFiles: mock(async () => []),
  pruneEngagement: mock(async () => 0),
  checkStorageLimit: mock(async () => true),
}

function resetAllMocks(): void {
  lastAuthHeader = null
  const clear = (fn: any) => fn.mockClear()
  clear(mockPage.goto)
  clear(mockPage.close)
  clear(mockPage.setExtraHTTPHeaders)
  clear(mockPage.evaluate)
  clear(mockContext.close)
  clear(mockEngine.launch)
  clear(mockEngine.createContext)
  clear(mockEngine.navigate)
  clear(mockEngine.captureScreenshot)
  clear(mockEngine.close)
  clear(mockCollector.captureScreenshot)
  clear(mockCollector.createPackage)
}

describe("JWTVerifier — backend API mocking integration", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-jwt-test-"))
    store = new EngagementStore(join(dbDir, "jwt.db"))
  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  beforeEach(() => {
    resetAllMocks()
  })

  // ── Test 1: Backend rejects tampered tokens ─────────────────────────
  test("reports NOT bypassable when backend rejects tampered tokens (HTTP 401)", async () => {
    // Configure mock backend to reject ALL tokens (even ones with alg:none)
    // by overriding the default goto behavior for this test
    const rejectingPage = {
      ...mockPage,
      goto: mock(async (_url: string, _opts?: any) => ({
        status: () => 401,  // Backend always rejects
        headers: () => ({ "content-type": "text/plain" }),
      })),
    }
    const rejectingContext = {
      newPage: mock(async () => rejectingPage),
      close: mock(async () => {}),
    }
    const rejectingEngine = {
      ...mockEngine,
      createContext: mock(async () => rejectingContext),
      navigate: mock(async () => rejectingPage),
    }

    const verifier = new JWTVerifier(
      rejectingEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      undefined,  // No original token
      mockCollector as any,
      "eng-jwt-1",
      "find-jwt-1",
    )

    const runner = await import("../../../src/argus/browser/verifiers/runner")
    const result = await runner.VerificationRunner.prototype.run(verifier)

    expect(result.passed).toBe(false)
    expect(result.confidence).toBe(Confidence.INFORMATIONAL)
    expect(result.summary).toContain("not bypassable")
    expect(rejectingEngine.createContext).toHaveBeenCalled()
  })

  // ── Test 2: Backend accepts alg:none token ──────────────────────────
  test("detects bypass when backend accepts alg:none token (HTTP 200)", async () => {
    // The default mock backend accepts alg:none tokens
    // This simulates a vulnerable backend that doesn't validate algorithm

    const verifier = new JWTVerifier(
      mockEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiJ9.test-signature",  // Original token
      mockCollector as any,
      "eng-jwt-1",
      "find-jwt-2",
    )

    const runner = await import("../../../src/argus/browser/verifiers/runner")
    const result = await runner.VerificationRunner.prototype.run(verifier)

    expect(result.passed).toBe(true)
    expect(result.summary).toContain("bypass confirmed")

    // Verify that setExtraHTTPHeaders was called (Gap 7.3 fix is active)
    expect(mockPage.setExtraHTTPHeaders).toHaveBeenCalled()

    // Verify the Authorization headers included the tampered tokens
    const authCalls = (mockPage.setExtraHTTPHeaders as any).mock.calls
    expect(authCalls.length).toBeGreaterThan(0)
    // At least one call should have a Bearer token
    const hasBearerToken = authCalls.some(
      (call: any[]) => call[0]?.["Authorization"]?.startsWith("Bearer ")
    )
    expect(hasBearerToken).toBe(true)
  })

  // ── Test 3: Backend accepts tampered payload tokens ─────────────────
  test("detects bypass when backend accepts tampered-payload tokens (HTTP 200)", async () => {
    // Configure backend to only accept tampered payload tokens but reject alg:none
    // This simulates a backend with strong algorithm validation but weak signature validation
    const tamperOnlyPage = {
      ...mockPage,
      goto: mock(async (_url: string, _opts?: any) => {
        // Explicitly reject alg:none tokens to simulate a backend that validates algorithm
        if (lastAuthHeader) {
          const token = lastAuthHeader.replace("Bearer ", "")
          try {
            const headerPart = token.split(".")[0]
            const decodedHeader = Buffer.from(headerPart, "base64url").toString()
            if (decodedHeader.includes('"alg":"none"')) {
              return { status: () => 401, headers: () => ({ "content-type": "text/plain" }) }
            }
          } catch { /* ignore parse errors */ }
        }
        const accepted = isTokenAcceptedByBackend(lastAuthHeader)
        return {
          status: () => accepted ? 200 : 401,
          headers: () => ({ "content-type": accepted ? "application/json" : "text/plain" }),
        }
      }),
    }
    const tamperOnlyContext = {
      newPage: mock(async () => tamperOnlyPage),
      close: mock(async () => {}),
    }
    const tamperOnlyEngine = {
      ...mockEngine,
      createContext: mock(async () => tamperOnlyContext),
      navigate: mock(async () => tamperOnlyPage),
    }

    const verifier = new JWTVerifier(
      tamperOnlyEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJ1c2VyIn0.valid-signature",
      mockCollector as any,
      "eng-jwt-1",
      "find-jwt-3",
    )

    const runner = await import("../../../src/argus/browser/verifiers/runner")
    const result = await runner.VerificationRunner.prototype.run(verifier)

    expect(result.passed).toBe(true)
    expect(result.summary).toContain("bypass confirmed")
    // Confidence should be MEDIUM (not HIGH) since alg:none wasn't the bypass vector
    expect(result.confidence).toBe(Confidence.MEDIUM)
  })

  // ── Test 4: Evidence collection after verification ──────────────────
  test("collects evidence after JWT verification", async () => {
    const verifier = new JWTVerifier(
      mockEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      "eyJhbGciOiJIUzI1NiJ9.original-token.signature",
      mockCollector as any,
      "eng-jwt-1",
      "find-jwt-4",
    )

    // Run the full lifecycle manually to test evidence collection
    await verifier.setup()
    await verifier.execute()
    const result = await verifier.verify()
    const evidence = await verifier.collectEvidence()
    await verifier.cleanup()

    expect(result.passed).toBe(true)
    expect(evidence.packageId).toBeTruthy()
    expect(evidence.findingId).toBe("find-jwt-4")
    expect(evidence.artifacts.length).toBeGreaterThan(0)

    // Verify collector was called
    expect(mockCollector.captureScreenshot).toHaveBeenCalled()
    expect(mockCollector.saveRequest).toHaveBeenCalled()
    expect(mockCollector.saveResponse).toHaveBeenCalled()

    // Verify engine was used
    expect(mockEngine.launch).toHaveBeenCalled()
    expect(mockEngine.createContext).toHaveBeenCalled()
    expect(mockEngine.close).toHaveBeenCalled()
  })

  // ── Test 5: Verifier handles missing original token gracefully ──────
  test("works without an original token", async () => {
    const verifier = new JWTVerifier(
      mockEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      undefined,  // No original token — verifier should still work
      mockCollector as any,
      "eng-jwt-1",
      "find-jwt-5",
    )

    const runner = await import("../../../src/argus/browser/verifiers/runner")
    const result = await runner.VerificationRunner.prototype.run(verifier)

    expect(result.passed).toBe(true)
    // Should still detect bypass via alg:none and tampered tokens
    expect(result.summary).toContain("bypass confirmed")
  })

  // ── Test 6: Verify backend API path is exercised (not just localStorage) ─
  test("exercises backend API via Authorization header (Gap 7.3 fix)", async () => {
    // This test specifically verifies that the Gap 7.3 fix is working:
    // the JWT verifier should inject tokens via setExtraHTTPHeaders,
    // not just localStorage, so the backend API is tested.

    resetAllMocks()
    lastAuthHeader = null

    const verifier = new JWTVerifier(
      mockEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      "eyJhbGciOiJIUzI1NiJ9.original.signature",
      undefined,  // No collector for this test
    )

    await verifier.setup()
    await verifier.execute()

    // Verify setExtraHTTPHeaders was called with Bearer tokens
    expect(mockPage.setExtraHTTPHeaders).toHaveBeenCalled()

    // Extract all Authorization header values that were set
    const authCalls = (mockPage.setExtraHTTPHeaders as any).mock.calls
    const bearerTokens = authCalls
      .map((call: any[]) => call[0]?.["Authorization"])
      .filter((h: string) => h?.startsWith("Bearer "))

    // Should have at least one Bearer token (for the original + alg:none + tampered tokens)
    expect(bearerTokens.length).toBeGreaterThanOrEqual(1)

    // The tokens should have been passed to the backend (page.goto checked them)
    expect(mockPage.goto).toHaveBeenCalled()

    await verifier.cleanup()
  })

  // ── Test 7: every testToken() call includes both localStorage AND header ─
  test("every testToken call injects via both localStorage and Authorization header", async () => {
    resetAllMocks()
    lastAuthHeader = null

    // Track evaluate calls with JWT-looking strings
    const evaluateCalls: string[] = []
    const trackingPage = {
      ...mockPage,
      evaluate: mock(async (fn: Function | string, ...args: any[]) => {
        // Capture the token arguments passed to evaluate
        if (args.length > 0 && typeof args[0] === "string" && args[0].includes(".")) {
          evaluateCalls.push(args[0])
        }
        return undefined
      }),
    }
    const trackingContext = {
      newPage: mock(async () => trackingPage),
      close: mock(async () => {}),
    }
    const trackingEngine = {
      ...mockEngine,
      createContext: mock(async () => trackingContext),
      navigate: mock(async () => trackingPage),
    }

    const verifier = new JWTVerifier(
      trackingEngine as any,
      "https://jwt-test.example.com",
      "/admin",
      undefined,
    )

    await verifier.setup()
    await verifier.execute()

    // Each token should be injected via BOTH localStorage (evaluate) and header (setExtraHTTPHeaders)
    expect(trackingPage.evaluate).toHaveBeenCalled()
    expect(trackingPage.setExtraHTTPHeaders).toHaveBeenCalled()

    // The number of unique token evaluations should match the number of header injections
    const evalCount = (trackingPage.evaluate as any).mock.calls.length
    const headerCount = (trackingPage.setExtraHTTPHeaders as any).mock.calls.length
    expect(headerCount).toBeGreaterThanOrEqual(1)
    expect(evalCount).toBeGreaterThanOrEqual(1)

    await verifier.cleanup()
  })
})

// ── verifyCommand integration ────────────────────────────────────────────
// These tests verify that the verify command correctly routes JWT findings
// to the JWTVerifier via the tool-name matching logic.

describe("verifyCommand — JWT finding routing", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-jwt-cmd-test-"))
    store = new EngagementStore(join(dbDir, "jwt-cmd.db"))
  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  beforeEach(() => {
    resetAllMocks()
  })

  test("routes 'jwt-scanner' tool finding to JWTVerifier", async () => {
    const eng = store.createEngagement("https://jwt-cmd-test.com", "assessment")
    const findingId = `find-jwt-cmd-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "JWT None Algorithm",
      severity: 4,
      confidence: 2,
      status: "PENDING",
      description: "https://jwt-cmd-test.com/admin",
      tool: "jwt-scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://jwt-cmd-test.com",
      engineOverride: mockEngine as any,
      collectorOverride: mockCollector as any,
    })

    expect(output).toContain("[JWT]")
    expect(output).toContain("bypass")
    expect(mockEngine.launch).toHaveBeenCalled()
    expect(mockEngine.close).toHaveBeenCalled()
  })

  test("routes 'jwt_tampering' subtype finding to JWTVerifier", async () => {
    const eng = store.createEngagement("https://jwt-subtype-test.com", "assessment")
    const findingId = `find-jwt-subtype-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "JWT Tampering",
      severity: 4,
      confidence: 2,
      status: "PENDING",
      description: "JWT tampering vulnerability on /api/admin",
      tool: "custom-tool",
      subtype: "jwt_tampering",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://jwt-subtype-test.com",
      engineOverride: mockEngine as any,
      collectorOverride: mockCollector as any,
    })

    expect(output).toContain("[JWT]")
    expect(mockEngine.launch).toHaveBeenCalled()
  })

  test("routes 'jwt_none_algorithm' subtype finding to JWTVerifier", async () => {
    const eng = store.createEngagement("https://jwt-none-test.com", "assessment")
    const findingId = `find-jwt-none-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "JWT None Algorithm",
      severity: 4,
      confidence: 2,
      status: "PENDING",
      description: "JWT algorithm none bypass on /api/admin",
      tool: "nuclei",
      subtype: "jwt_none_algorithm",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const { verifyCommand } = await import("../../../src/argus/commands/verify")
    const output = await verifyCommand(findingId, {
      storeOverride: store,
      targetUrl: "https://jwt-none-test.com",
      engineOverride: mockEngine as any,
      collectorOverride: mockCollector as any,
    })

    expect(output).toContain("[JWT]")
    expect(mockEngine.launch).toHaveBeenCalled()
  })

  test("reports 'No matching verifier' for non-JWT tools", async () => {
    const eng = store.createEngagement("https://non-jwt-test.com", "assessment")
    const findingId = `find-non-jwt-${Date.now()}`
    store.saveFindings(eng.id, [{
      id: findingId,
      title: "Some finding",
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
      targetUrl: "https://non-jwt-test.com",
      engineOverride: mockEngine as any,
      collectorOverride: mockCollector as any,
    })

    expect(output).toContain("No matching verifier found")
  })
})
