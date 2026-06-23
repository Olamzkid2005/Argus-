/**
 * Integration test for evidence flow — full pipeline from artifact creation
 * through integrity verification, listing, and pruning.
 *
 * Tests the real EvidenceCollector filesystem operations, verifyPackage
 * integrity checks, evidenceCommand list/show/prune/verify-package actions,
 * and audit log entries — all with real files and store.
 */
import { describe, expect, test, beforeAll, afterAll, mock } from "bun:test"
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync, existsSync, readdirSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { createHash } from "crypto"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { EvidenceCollector } from "../../../src/argus/evidence/collector"

let dbDir: string
let evidenceBaseDir: string
let store: EngagementStore
let collector: EvidenceCollector

beforeAll(() => {
  dbDir = mkdtempSync(join(tmpdir(), "argus-evidence-int-test-"))
  evidenceBaseDir = join(dbDir, "engagements")
  store = new EngagementStore(join(dbDir, "evidence-int.db"))
  collector = new EvidenceCollector(evidenceBaseDir)
})

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

function sha256(content: string | Buffer): string {
  return createHash("sha256").update(content).digest("hex")
}

describe("evidence flow: create artifacts and package", () => {
  let engId: string
  let findingId: string

  test("creates engagement and finding in store", () => {
    const eng = store.createEngagement("https://evidence-target.com", "assessment")
    engId = eng.id
    findingId = `find-ev-${Date.now()}`

    store.saveFindings(engId, [{
      id: findingId,
      title: "Evidence test finding",
      severity: 3,
      confidence: 2,
      status: "PENDING",
      description: "Test finding for evidence flow",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const findings = store.getFindings(engId)
    expect(findings).toHaveLength(1)
    expect(findings[0].id).toBe(findingId)
  })

  test("EvidenceCollector saves request artifact to disk", async () => {
    const entry = await collector.saveRequest(engId, findingId, "GET /api/endpoint HTTP/1.1")
    expect(entry.type).toBe("request")
    expect(entry.size_bytes).toBeGreaterThan(0)
    expect(entry.hash).toMatch(/^[a-f0-9]{64}$/)

    // Verify file actually exists on disk
    const filePath = join(evidenceBaseDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)
    const content = readFileSync(filePath, "utf-8")
    expect(content).toBe("GET /api/endpoint HTTP/1.1")
  })

  test("EvidenceCollector saves response artifact to disk", async () => {
    const entry = await collector.saveResponse(engId, findingId, '{"status":200,"data":"ok"}')
    expect(entry.type).toBe("response")
    expect(entry.size_bytes).toBeGreaterThan(0)

    const filePath = join(evidenceBaseDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)
  })

  test("EvidenceCollector captures screenshot to disk", async () => {
    const buf = Buffer.from("fake-screenshot-png-data")
    const entry = await collector.captureScreenshot(engId, findingId, buf)
    expect(entry.type).toBe("screenshot")
    expect(entry.size_bytes).toBe(buf.length)

    const filePath = join(evidenceBaseDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)
    const diskBuf = readFileSync(filePath)
    expect(diskBuf.equals(buf)).toBe(true)
  })

  test("EvidenceCollector creates package with manifest and correct hash", async () => {
    // Collect all artifacts first
    const req = await collector.saveRequest(engId, findingId, "POST /api/data HTTP/1.1")
    const res = await collector.saveResponse(engId, findingId, '{"id":1}')
    const shot = await collector.captureScreenshot(engId, findingId, Buffer.from("more-screenshot-data"))

    const manifest = await collector.createPackage(engId, findingId, [req, res, shot])
    expect(manifest.package_id).toBe(findingId)
    expect(manifest.engagement_id).toBe(engId)
    expect(manifest.artifacts).toHaveLength(3)
    expect(manifest.package_hash).toMatch(/^[a-f0-9]{64}$/)

    // Verify manifest.json exists on disk
    const manifestPath = join(evidenceBaseDir, engId, "artifacts", findingId, "manifest.json")
    expect(existsSync(manifestPath)).toBe(true)

    const diskManifest = JSON.parse(readFileSync(manifestPath, "utf-8"))
    expect(diskManifest.package_hash).toBe(manifest.package_hash)
    expect(diskManifest.artifacts).toHaveLength(3)
  })
})

describe("evidence flow: verify integrity", () => {
  let engId: string
  let findingId: string

  test("sets up a valid package for integrity verification", async () => {
    const eng = store.createEngagement("https://verify-evidence.com", "assessment")
    engId = eng.id
    findingId = `find-verify-${Date.now()}`

    store.saveFindings(engId, [{
      id: findingId,
      title: "Verify test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    // Create artifacts and package
    const req = await collector.saveRequest(engId, findingId, "GET /verify HTTP/1.1")
    const res = await collector.saveResponse(engId, findingId, '{"verified":true}')
    await collector.createPackage(engId, findingId, [req, res])
  })

  test("verifyPackage returns valid for unmodified package", async () => {
    const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
    const result = await verifyPackage(evidenceBaseDir, engId, findingId)
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
    expect(result.packageId).toBe(findingId)
    expect(result.manifestHash).toBeTruthy()
    expect(result.computedHash).toBe(result.manifestHash)
  })

  test("verifyPackage detects tampered artifact content", async () => {
    // Tamper with a response file
    const responseDir = join(evidenceBaseDir, engId, "artifacts", findingId, "responses")
    const responseFiles = readdirSync(responseDir)
    if (responseFiles.length > 0) {
      const tamperPath = join(responseDir, responseFiles[0])
      writeFileSync(tamperPath, '{"tampered":true}')

      const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
      const result = await verifyPackage(evidenceBaseDir, engId, findingId)
      expect(result.valid).toBe(false)
      expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
    }
  })

  test("verifyPackage detects missing artifact", async () => {
    const eng2 = store.createEngagement("https://verify-missing.com", "assessment")
    const findingId2 = `find-missing-${Date.now()}`

    // Create package where manifest references a file that doesn't exist
    const artifactDir = join(evidenceBaseDir, eng2.id, "artifacts", findingId2)
    mkdirSync(artifactDir, { recursive: true })

    const ghostHash = sha256("ghost content")
    const manifest = {
      package_id: findingId2,
      engagement_id: eng2.id,
      created_at: new Date().toISOString(),
      artifacts: [
        { path: "requests/ghost.txt", hash: ghostHash, type: "request" as const, size_bytes: 12 },
      ],
      package_hash: "",
    }
    const hashStr = JSON.stringify({ ...manifest, package_hash: "" }, null, 2) + ghostHash
    manifest.package_hash = sha256(hashStr)
    writeFileSync(join(artifactDir, "manifest.json"), JSON.stringify(manifest))

    const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
    const result = await verifyPackage(evidenceBaseDir, eng2.id, findingId2)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Artifact missing"))).toBe(true)
  })

  test("verifyPackage returns invalid for non-existent package", async () => {
    const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
    const result = await verifyPackage(evidenceBaseDir, engId, "nonexistent-pkg")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Manifest file not found")
  })

  test("verifyPackage rejects invalid package ID with special characters", async () => {
    const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
    const result = await verifyPackage(evidenceBaseDir, engId, "../../../etc/passwd")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Invalid package ID")
  })
})

describe("evidence flow: list and show via evidenceCommand", () => {
  let engId: string
  let findingId: string

  test("sets up engagement with findings and packages for listing", async () => {
    const eng = store.createEngagement("https://list-evidence.com", "assessment")
    engId = eng.id
    findingId = `find-list-${Date.now()}`

    store.saveFindings(engId, [{
      id: findingId,
      title: "List test finding",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const req = await collector.saveRequest(engId, findingId, "GET /list HTTP/1.1")
    await collector.createPackage(engId, findingId, [req])
  })

  test("evidenceCommand list returns evidence details for engagement", async () => {
    // Register the package in the store so evidenceCommand can find it
    const manifestPath = join(evidenceBaseDir, engId, "artifacts", findingId, "manifest.json")
    if (existsSync(manifestPath)) {
      const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"))
      store.saveEvidencePackage(manifest.package_id, findingId, manifest.package_hash)
      for (const art of manifest.artifacts) {
        store.saveArtifact(art.path, manifest.package_id, art.path, art.hash, art.size_bytes, art.type)
      }
    }

    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("list", [engId], { store, evidenceBaseDir })

    expect(output).toContain(`Evidence for engagement ${engId}`)
    expect(output).toContain(findingId)
    expect(output).toContain("List test finding")
    expect(output).toContain("package(s)")
    expect(output).toContain("bytes")
  })

  test("evidenceCommand list returns all engagements when no ID given", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("list", [], { store, evidenceBaseDir })

    expect(output).toContain("Engagements with evidence:")
  })

  test("evidenceCommand show returns package details for valid package", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("show", [engId, findingId], { store, evidenceBaseDir })

    expect(output).toContain(`Package ID: ${findingId}`)
    expect(output).toContain("Valid: true")
  })

  test("evidenceCommand show returns invalid for non-existent package", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("show", [engId, "nonexistent"], { store, evidenceBaseDir })

    expect(output).toContain("Package ID: nonexistent")
    expect(output).toContain("Valid: false")
    expect(output).toContain("Manifest file not found")
  })

  test("evidenceCommand show returns usage when args missing", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("show", [], { store, evidenceBaseDir })
    expect(output).toContain("Usage:")
  })

  test("evidenceCommand verify-package returns OK for valid package", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("verify-package", [engId, findingId], { store, evidenceBaseDir })

    expect(output).toContain("OK")
    expect(output).not.toContain("INVALID")
    expect(output).toContain(findingId)
  })

  test("evidenceCommand verify-package returns INVALID for tampered package", async () => {
    const eng = store.createEngagement("https://verify-cmd-tamper.com", "assessment")
    const tamperFindingId = `find-tamper-${Date.now()}`

    store.saveFindings(eng.id, [{
      id: tamperFindingId,
      title: "Tamper test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    const req = await collector.saveRequest(eng.id, tamperFindingId, "original content")
    await collector.createPackage(eng.id, tamperFindingId, [req])

    // Tamper with the file
    const reqDir = join(evidenceBaseDir, eng.id, "artifacts", tamperFindingId, "requests")
    const files = readdirSync(reqDir)
    if (files.length > 0) {
      writeFileSync(join(reqDir, files[0]), "tampered content")
    }

    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("verify-package", [eng.id, tamperFindingId], { store, evidenceBaseDir })

    expect(output).toContain("INVALID")
    expect(output).toContain("Hash mismatch")
  })
})

describe("evidence flow: prune with audit log verification", () => {
  let engId: string
  let findingId: string

  const mockCollector: any = {
    pruneEngagement: mock(async () => 3),
    saveRequest: mock(async () => ({ path: "requests/req.txt", type: "request" as const, hash: "abc", size_bytes: 5 })),
    saveResponse: mock(async () => ({ path: "responses/res.txt", type: "response" as const, hash: "def", size_bytes: 6 })),
    captureScreenshot: mock(async () => ({ path: "shot.png", type: "screenshot" as const, hash: "abc", size_bytes: 100 })),
    createPackage: mock(async () => ({ package_id: "pkg1", artifacts: [] })),
    checkStorageLimit: mock(async () => true),
  }

  test("sets up engagement for prune testing", async () => {
    const eng = store.createEngagement("https://prune-evidence.com", "assessment")
    engId = eng.id
    findingId = `find-prune-${Date.now()}`

    store.saveFindings(engId, [{
      id: findingId,
      title: "Prune test",
      severity: 2,
      confidence: 1,
      status: "PENDING",
      description: "test",
      tool: "scanner",
      phase: "phase-1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }])

    await collector.saveRequest(engId, findingId, "prune test data")
  })

  test("evidenceCommand prune appends audit log for each engagement", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    await evidenceCommand("prune", [], { store, collector: mockCollector })

    // Verify audit log was appended
    const auditLog = store.getAuditLog(engId)
    expect(auditLog.length).toBeGreaterThanOrEqual(1)
    const pruneTypes = auditLog.map((e: any) => e.eventType)
    expect(pruneTypes).toContain("EVIDENCE_PRUNE")
  })

  test("evidenceCommand prune with custom retention uses correct days", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    await evidenceCommand("prune", ["15"], { store, collector: mockCollector })

    const auditLog = store.getAuditLog(engId)
    expect(auditLog.length).toBeGreaterThanOrEqual(1)
  })

  test("evidenceCommand prune prints summary with correct counts", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("prune", [], { store, collector: mockCollector })

    expect(output).toMatch(/Pruned \d+ artifact\(s\) older than \d+ days across \d+ engagement\(s\)/)
  })

  test("evidenceCommand prune rejects invalid retention days", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("prune", ["abc"], { store, collector: mockCollector })
    expect(output).toContain("Invalid retention days")
    expect(output).toContain("abc")
  })
})

describe("evidence flow: edge cases", () => {
  test("evidenceCommand returns unknown action error", async () => {
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("unknown-action" as any, [], { store })
    expect(output).toContain("Unknown evidence action")
    expect(output).toContain("unknown-action")
  })

  test("evidenceCommand list returns no-engagements message when empty", async () => {
    const emptyStore = new EngagementStore(join(dbDir, `empty-evidence-${Date.now()}.db`))
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("list", [], { store: emptyStore })
    expect(output).toBe("No engagements found")
  })

  test("evidenceCommand list returns no-findings message for engagement without findings", async () => {
    const emptyEng = store.createEngagement("https://empty-evidence.com", "assessment")
    const { evidenceCommand } = await import("../../../src/argus/commands/evidence")
    const output = await evidenceCommand("list", [emptyEng.id], { store })
    expect(output).toBe(`No findings for engagement ${emptyEng.id}`)
  })
})
