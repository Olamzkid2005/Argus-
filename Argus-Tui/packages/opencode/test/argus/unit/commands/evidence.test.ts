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

let mockVerifyPackageResult: any = {
  valid: true,
  packageId: "pkg-test-123",
  manifestHash: "abc123def456",
  computedHash: "abc123def456",
  errors: [],
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
      })),
    }))

    mock.module("../../../../src/argus/evidence/integrity", () => ({
      verifyPackage: mock((baseDir: string, packageId: string) => ({
        ...mockVerifyPackageResult,
        packageId,
      })),
    }))


  })

  afterAll(() => {
    try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
  })

  afterEach(() => {
    mockVerifyPackageResult = {
      valid: true,
      packageId: "pkg-test-123",
      manifestHash: "abc123def456",
      computedHash: "abc123def456",
      errors: [],
    }
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

    test("shows package details for valid package-id", async () => {
      mockVerifyPackageResult = {
        valid: true,
        packageId: "pkg-abc",
        manifestHash: "hash123",
        computedHash: "hash123",
        errors: [],
      }

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["pkg-abc"])

      expect(output).toContain("Package ID: pkg-abc")
      expect(output).toContain("Valid: true")
    })

    test("shows errors for invalid package", async () => {
      mockVerifyPackageResult = {
        valid: false,
        packageId: "pkg-bad",
        manifestHash: "",
        computedHash: "different",
        errors: ["Hash mismatch", "Artifact missing"],
      }

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["pkg-bad"])

      expect(output).toContain("Package ID: pkg-bad")
      expect(output).toContain("Valid: false")
      expect(output).toContain("Hash mismatch")
      expect(output).toContain("Artifact missing")
    })
  })

  describe("verify-package", () => {
    test("returns usage message when no package-id provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", [])
      expect(output).toBe("Usage: evidence verify-package <package-id>")
    })

    test("returns OK for valid package", async () => {
      mockVerifyPackageResult = {
        valid: true,
        packageId: "pkg-valid-1",
        manifestHash: "abc123",
        computedHash: "abc123",
        errors: [],
      }

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-valid-1"])

      expect(output).toContain("OK")
      expect(output).toContain("abc123")
    })

    test("returns INVALID with errors for invalid package", async () => {
      mockVerifyPackageResult = {
        valid: false,
        packageId: "pkg-invalid-1",
        manifestHash: "",
        computedHash: "wrong",
        errors: ["Package hash does not match computed hash"],
      }

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-invalid-1"])

      expect(output).toContain("INVALID")
      expect(output).toContain("Package hash does not match computed hash")
    })

    test("reports each integrity error on its own line", async () => {
      mockVerifyPackageResult = {
        valid: false,
        packageId: "pkg-multi-err",
        manifestHash: "",
        computedHash: "",
        errors: ["Artifact missing: screenshot.png", "Hash mismatch for request.txt"],
      }

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["pkg-multi-err"])

      expect(output).toContain("Artifact missing: screenshot.png")
      expect(output).toContain("Hash mismatch for request.txt")
      expect(output.split("\n").length).toBeGreaterThanOrEqual(3)
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
