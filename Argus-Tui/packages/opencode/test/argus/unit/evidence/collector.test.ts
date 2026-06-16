import { describe, expect, test, afterAll } from "bun:test"
import { mkdtempSync, rmSync, readFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { createHash } from "crypto"
import { EvidenceCollector } from "../../../../src/argus/evidence/collector"

const baseDir = mkdtempSync(join(tmpdir(), "collector-test-"))

afterAll(() => { rmSync(baseDir, { recursive: true, force: true }) })

describe("EvidenceCollector", () => {
  test("saveRequest creates artifact entry with correct path, hash, type, size", async () => {
    const collector = new EvidenceCollector(baseDir)
    const entry = await collector.saveRequest("eng-1", "find-1", "test request body")
    expect(entry.type).toBe("request")
    expect(entry.path).toMatch(/^requests[\\\/]request-\d+-[a-f0-9]+\.txt$/)
    expect(entry.size_bytes).toBe(17)
    expect(entry.hash).toMatch(/^[a-f0-9]{64}$/)
  })

  test("saveResponse creates artifact entry", async () => {
    const collector = new EvidenceCollector(baseDir)
    const entry = await collector.saveResponse("eng-1", "find-2", "test response body")
    expect(entry.type).toBe("response")
    expect(entry.path).toMatch(/^responses[\\\/]response-\d+-[a-f0-9]+\.txt$/)
    expect(entry.size_bytes).toBe(18)
    expect(entry.hash).toMatch(/^[a-f0-9]{64}$/)
  })

  test("captureScreenshot saves buffer and returns correct entry", async () => {
    const collector = new EvidenceCollector(baseDir)
    const buf = Buffer.from("fake-png-data")
    const entry = await collector.captureScreenshot("eng-1", "find-3", buf)
    expect(entry.type).toBe("screenshot")
    expect(entry.path).toMatch(/^screenshots[\\\/]screenshot-\d+-[a-f0-9]+\.png$/)
    expect(entry.size_bytes).toBe(13)
    expect(entry.hash).toMatch(/^[a-f0-9]{64}$/)
    const expectedHash = createHash("sha256").update(buf).digest("hex")
    expect(entry.hash).toBe(expectedHash)
  })

  test("createPackage generates manifest with package_hash", async () => {
    const collector = new EvidenceCollector(baseDir)
    const artifact = await collector.saveRequest("eng-1", "find-4", "data")
    const manifest = await collector.createPackage("eng-1", "find-4", [artifact])
    expect(manifest.package_id).toBe("find-4")
    expect(manifest.engagement_id).toBe("eng-1")
    expect(manifest.artifacts).toHaveLength(1)
    expect(manifest.package_hash).toMatch(/^[a-f0-9]{64}$/)
    expect(manifest.created_at).toBeTruthy()
  })

  test("createPackage writes manifest.json to disk", async () => {
    const collector = new EvidenceCollector(baseDir)
    const artifact = await collector.saveRequest("eng-1", "find-5", "data")
    const manifest = await collector.createPackage("eng-1", "find-5", [artifact])
    const manifestPath = join(baseDir, "eng-1", "artifacts", "find-5", "manifest.json")
    const content = JSON.parse(readFileSync(manifestPath, "utf-8"))
    expect(content.package_id).toBe(manifest.package_id)
    expect(content.package_hash).toBe(manifest.package_hash)
    expect(content.artifacts).toHaveLength(1)
  })

  test("hashFile produces consistent SHA-256", async () => {
    const collector = new EvidenceCollector(baseDir)
    const entry = await collector.saveRequest("eng-1", "find-6", "consistent content")
    const filePath = join(baseDir, "eng-1", "artifacts", "find-6", entry.path)
    const diskContent = readFileSync(filePath)
    const expectedHash = createHash("sha256").update(diskContent).digest("hex")
    expect(entry.hash).toBe(expectedHash)
  })

  test("Handles multiple artifacts in one package", async () => {
    const collector = new EvidenceCollector(baseDir)
    const a1 = await collector.saveRequest("eng-1", "find-7", "req")
    const a2 = await collector.saveResponse("eng-1", "find-7", "res")
    const a3 = await collector.captureScreenshot("eng-1", "find-7", Buffer.from("img"))
    const manifest = await collector.createPackage("eng-1", "find-7", [a1, a2, a3])
    expect(manifest.artifacts).toHaveLength(3)
    expect(manifest.package_hash).toMatch(/^[a-f0-9]{64}$/)
  })

  test("Files are actually written to disk", async () => {
    const collector = new EvidenceCollector(baseDir)
    const entry = await collector.saveRequest("eng-1", "find-8", "disk check")
    const filePath = join(baseDir, "eng-1", "artifacts", "find-8", entry.path)
    const content = readFileSync(filePath, "utf-8")
    expect(content).toBe("disk check")
  })
})
