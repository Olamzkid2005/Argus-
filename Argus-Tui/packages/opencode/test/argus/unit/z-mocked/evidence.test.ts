import { describe, expect, test, beforeAll, afterAll, afterEach, mock } from "bun:test"
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../../src/argus/engagement/store"
import type { EvidenceCollector } from "../../../../src/argus/evidence/collector"

let dbDir: string
let store: EngagementStore
let mockCollector: EvidenceCollector

function makeStore(name: string): EngagementStore {
  return new EngagementStore(join(dbDir, `${name}.db`))
}

let mockPruneReturn = 5

describe("evidenceCommand", () => {
  beforeAll(() => {
    dbDir = mkdtempSync(join(tmpdir(), "argus-evidence-test-"))
    store = makeStore("evidence")

    mockCollector = {
      pruneEngagement: mock(async () => mockPruneReturn),
      saveRequest: mock(async () => ({ path: "requests/req.txt", type: "request" as const, hash: "abc", size_bytes: 5 })),
      saveResponse: mock(async () => ({ path: "responses/res.txt", type: "response" as const, hash: "def", size_bytes: 6 })),
      captureScreenshot: mock(async () => ({ path: "shot.png", type: "screenshot" as const, hash: "abc", size_bytes: 100 })),
      createPackage: mock(async () => ({ package_id: "pkg1", artifacts: [{ path: "req.txt", type: "request" as const, hash: "abc", size_bytes: 5 }] })),
      checkStorageLimit: mock(async () => true),
    } as unknown as EvidenceCollector
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
      const output = await evidenceCommand("list", [], { store })
      expect(typeof output).toBe("string")
    })

    test("returns no-findings message for engagement ID with no findings", async () => {
      const eng = store.createEngagement("https://empty-eng.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [eng.id], { store })

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
      const output = await evidenceCommand("list", [eng.id], { store })

      expect(output).toContain(`Evidence for engagement ${eng.id}`)
      expect(output).toContain(`${tag}-f1`)
      expect(output).toContain("0 package(s)")
    })

    test("lists all engagements when no engagement ID provided", async () => {
      store.createEngagement("https://list-all-test.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("list", [], { store })

      expect(output).toContain("Engagements with evidence:")
    })
  })

  describe("show", () => {
    test("returns usage message when no args provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", [], { store })
      expect(output).toContain("Usage:")
    })

    test("returns usage message when no package-id provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["eng-1"], { store })
      expect(output).toContain("Usage:")
    })

    test("shows package details for non-existent package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("show", ["eng-fake", "pkg-abc"], { store })

      expect(output).toContain("Package ID: pkg-abc")
      expect(output).toContain("Manifest file not found")
    })
  })

  describe("verify-package", () => {
    test("returns usage message when no package-id provided", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", [], { store })
      expect(output).toContain("Usage:")
    })

    test("returns INVALID for nonexistent package", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", ["nonexistent-eng", "nonexistent-pkg"], { store })

      expect(output).toContain("INVALID")
      expect(output).toContain("not found")
    })

    test("creates and verifies a valid package successfully", async () => {
      const eng = store.createEngagement("https://verify-test.com", "assessment")
      const findingId = `find-verify-${Date.now()}`
      store.saveFindings(eng.id, [{
        id: findingId, title: "Test", severity: 2, confidence: 2,
        status: "PENDING", description: "test", tool: "nuclei", phase: "phase-1",
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      }])

      const evidenceBaseDir = join(dbDir, "engagements")
      const artifactDir = join(evidenceBaseDir, eng.id, "artifacts", findingId)
      mkdirSync(artifactDir, { recursive: true })

      writeFileSync(join(artifactDir, "req.txt"), "request body")

      const { createHash } = await import("crypto")
      const fileHash = createHash("sha256").update("request body").digest("hex")
      const manifest = {
        package_id: findingId,
        engagement_id: eng.id,
        created_at: new Date().toISOString(),
        artifacts: [{ path: "req.txt", hash: fileHash, type: "request", size_bytes: 12 }],
        package_hash: "",
      }
      const manifestStr = JSON.stringify({ ...manifest, package_hash: "" }, null, 2) + fileHash
      manifest.package_hash = createHash("sha256").update(manifestStr).digest("hex")
      writeFileSync(join(artifactDir, "manifest.json"), JSON.stringify(manifest))

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("verify-package", [eng.id, findingId], {
        store,
        evidenceBaseDir,
      })

      expect(output).toContain("OK")
      expect(output).not.toContain("INVALID")
    })
  })

  describe("prune", () => {
    test("removes artifacts across all engagements with default retention", async () => {
      store.createEngagement("https://prune-test.com", "assessment")
      store.createEngagement("https://prune-test-2.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", [], { store, collector: mockCollector })

      expect(output).toMatch(/Pruned \d+ artifact\(s\) older than 30 days across \d+ engagement\(s\)/)
    })

    test("uses custom retention days when provided", async () => {
      store.createEngagement("https://prune-custom.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", ["15"], { store, collector: mockCollector })

      expect(output).toMatch(/Pruned \d+ artifact\(s\) older than 15 days across \d+ engagement\(s\)/)
    })

    test("returns error for non-numeric retention days", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", ["abc"], { store, collector: mockCollector })

      expect(output).toContain("Invalid retention days")
      expect(output).toContain("abc")
      expect(output).toContain("positive integer")
    })

    test("returns error for negative retention days", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", ["-5"], { store, collector: mockCollector })

      expect(output).toContain("Invalid retention days")
      expect(output).toContain("-5")
      expect(output).toContain("positive integer")
    })

    test("returns error for zero retention days", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", ["0"], { store, collector: mockCollector })

      expect(output).toContain("Invalid retention days")
      expect(output).toContain("0")
      expect(output).toContain("positive integer")
    })

    test("appends audit log for pruned engagements", async () => {
      const eng = store.createEngagement("https://prune-audit.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      await evidenceCommand("prune", [], { store, collector: mockCollector })

      const auditLog = store.getAuditLog(eng.id)
      expect(auditLog.some(e => e.eventType === "EVIDENCE_PRUNE")).toBe(true)
    })

    test("reports zero pruned when collector returns 0", async () => {
      mockPruneReturn = 0
      store.createEngagement("https://prune-zero.com", "assessment")

      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("prune", [], { store, collector: mockCollector })

      expect(output).toMatch(/Pruned 0 artifact/)
    })
  })

  describe("error handling", () => {
    test("returns error message for unknown action", async () => {
      const { evidenceCommand } = await import("../../../../src/argus/commands/evidence")
      const output = await evidenceCommand("unknown-action" as any, [], { store })
      expect(output).toContain("Unknown evidence action")
      expect(output).toContain("unknown-action")
    })
  })
})
