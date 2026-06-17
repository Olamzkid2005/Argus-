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

let mockPruneReturn = 5

describe("evidenceCommand", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-evidence-test-"))
    store = makeStore("evidence")

    mock.module("../../../../src/argus/engagement/store", () => ({
      EngagementStore: mock(() => store),
    }))

    mock.module("../../../../src/argus/evidence/collector", () => ({
      EvidenceCollector: mock(() => ({
        pruneEngagement: mock(async () => mockPruneReturn),
        saveRequest: mock(async () => ({ path: "requests/req.txt", type: "request" as const, hash: "abc", size_bytes: 5 })),
        saveResponse: mock(async () => ({ path: "responses/res.txt", type: "response" as const, hash: "def", size_bytes: 6 })),
        captureScreenshot: mock(async () => ({ path: "shot.png", type: "screenshot" as const, hash: "abc", size_bytes: 100 })),
        createPackage: mock(async () => ({ package_id: "pkg1", artifacts: [{ path: "req.txt", type: "request" as const, hash: "abc", size_bytes: 5 }] })),
        checkStorageLimit: mock(async () => true),
      })),
    }))

    // NOTE: verifyPackage is NOT mocked to avoid contaminating integrity.test.ts


  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  afterEach(() => {
    mockPruneReturn = 5
  })

  describe("list", () => {
    test("returns string output", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [])
      expect(typeof output).toBe("string")
    })

    test("returns no-findings message for engagement ID with no findings", async () => {
      const eng = store.createEngagement("https://empty-eng.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [eng.id])

      expect(output).toContain(`No findings for engagement ${eng.id}`)
    })

    test("shows evidence details for engagement with findings and packages", async () => {
      const tag = `list-${Date.now()}`
      const eng = store.createEngagement("https://list-test.com", "assessment")
      store.saveFindings(eng.id, [{
        id: `${tag}-f1`,
        title: "SQL Injection",
        severity: 4,
        confidence: 3,
        status: "CONFIRMED",
        description: "SQLi",
        tool: "nuclei",
        phase: "vuln_scan",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }])

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [eng.id])

      expect(output).toContain(`Evidence for engagement ${eng.id}`)
      expect(output).toContain(`${tag}-f1`)
      expect(output).toContain("0 package(s)")
    })

    test("lists all engagements when no engagement ID provided", async () => {
      store.createEngagement("https://list-all-test.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [])

      expect(output).toContain("Engagements with evidence:")
    })
  })

  describe("show", () => {
    test("returns usage message when no package-id provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", [])
      expect(output).toBe("Usage: evidence show <package-id>")
    })

    test("shows package details for package-id", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["pkg-abc"])

      expect(output).toContain("Package ID: pkg-abc")
      expect(output).toContain("not found")
    })

    test("shows errors for invalid package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["pkg-bad"])

      expect(output).toContain("Package ID: pkg-bad")
      expect(output).toContain("not found")
    })
  })

  describe("verify-package", () => {
    test("returns usage message when no package-id provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", [])
      expect(output).toBe("Usage: evidence verify-package <package-id>")
    })

    test("returns INVALID for nonexistent package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-valid-1"])

      expect(output).toContain("INVALID")
      expect(output).toContain("not found")
    })

    test("returns INVALID with errors for nonexistent package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-invalid-1"])

      expect(output).toContain("INVALID")
      expect(output).toContain("not found")
    })

    test("reports integrity error for nonexistent package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-multi-err"])

      expect(output).toContain("INVALID")
      expect(output).toContain("not found")
    })
  })

  describe("prune", () => {
    test("removes artifacts across all engagements with default retention", async () => {
      store.createEngagement("https://prune-test.com", "assessment")
      store.createEngagement("https://prune-test-2.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", [])

      expect(output).toMatch(/Pruned \d+ artifact\(s\) older than 30 days across \d+ engagement\(s\)/)
    })

    test("uses custom retention days when provided", async () => {
      store.createEngagement("https://prune-custom.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", ["15"])

      expect(output).toMatch(/Pruned \d+ artifact\(s\) older than 15 days across \d+ engagement\(s\)/)
    })

    test("appends audit log for pruned engagements", async () => {
      const eng = store.createEngagement("https://prune-audit.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      await evidenceCommand("prune", [])

      const auditLog = store.getAuditLog(eng.id)
      expect(auditLog.some(e => e.eventType === "EVIDENCE_PRUNE")).toBe(true)
    })

    test("reports zero pruned when collector returns 0", async () => {
      mockPruneReturn = 0
      store.createEngagement("https://prune-zero.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", [])

      expect(output).toMatch(/Pruned 0 artifact/)
    })
  })

  describe("error handling", () => {
    test("returns error message for unknown action", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("unknown-action" as any, [])
      expect(output).toContain("Unknown evidence action")
      expect(output).toContain("unknown-action")
    })
  })
})
