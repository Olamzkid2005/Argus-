import { describe, expect, test, afterAll } from "bun:test"
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { createHash } from "crypto"
import { verifyPackage } from "../../../../src/argus/evidence/integrity"
import type { EvidenceManifest, ArtifactEntry } from "../../../../src/argus/evidence/types"

const baseDir = mkdtempSync(join(tmpdir(), "integrity-test-"))

afterAll(() => { rmSync(baseDir, { recursive: true, force: true }) })

function sha256(content: string | Buffer): string {
  return createHash("sha256").update(content).digest("hex")
}

function setupPackage(
  packageId: string,
  artifacts: { path: string; content: string }[],
  engagementId: string = "eng-1",
): string {
  const artifactDir = join(baseDir, engagementId, "artifacts", packageId)
  mkdirSync(artifactDir, { recursive: true })

  const entries: ArtifactEntry[] = artifacts.map((a) => ({
    path: a.path,
    hash: sha256(a.content),
    type: "request" as const,
    size_bytes: Buffer.byteLength(a.content),
  }))

  for (const a of artifacts) {
    const subDir = join(artifactDir, a.path.split("/").slice(0, -1).join("/"))
    mkdirSync(subDir, { recursive: true })
    writeFileSync(join(artifactDir, a.path), a.content)
  }

  const manifest: EvidenceManifest = {
    package_id: packageId,
    engagement_id: "eng-1",
    created_at: new Date().toISOString(),
    artifacts: entries,
    package_hash: "",
  }

  const hashStr =
    JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
    entries.map((e) => e.hash).join("")
  manifest.package_hash = sha256(hashStr)

  writeFileSync(
    join(artifactDir, "manifest.json"),
    JSON.stringify(manifest, null, 2),
  )

  return packageId
}

describe("verifyPackage", () => {
  test("Returns invalid with error when manifest file not found", async () => {
    const result = await verifyPackage(baseDir, "eng-1", "nonexistent")
    expect(result.valid).toBe(false)
    expect(result.packageId).toBe("nonexistent")
    expect(result.errors).toContain("Manifest file not found")
  })

  test("Returns valid for a package with all artifacts present and matching hashes", async () => {
    const pkgId = setupPackage("valid-pkg", [
      { path: "requests/req.txt", content: "request data" },
      { path: "responses/res.txt", content: "response data" },
    ])
    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
    expect(result.packageId).toBe(pkgId)
    expect(result.manifestHash).toBeTruthy()
    expect(result.computedHash).toBe(result.manifestHash)
  })

  test("Detects missing artifacts", async () => {
    const pkgId = "missing-artifact"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(artifactDir, { recursive: true })

    const entryHash = sha256("file content that does not exist")
    const entries: ArtifactEntry[] = [
      {
        path: "requests/missing.txt",
        hash: entryHash,
        type: "request",
        size_bytes: 0,
      },
    ]

    const manifest: EvidenceManifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: entries,
      package_hash: "",
    }
    const hashStr =
      JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
      entries.map((e) => e.hash).join("")
    manifest.package_hash = sha256(hashStr)
    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Artifact missing"))).toBe(true)
  })

  test("Detects hash mismatches", async () => {
    const pkgId = "hash-mismatch"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(join(artifactDir, "requests"), { recursive: true })
    writeFileSync(join(artifactDir, "requests", "file.txt"), "real content")

    const wrongHash = sha256("different content")
    const entries: ArtifactEntry[] = [
      {
        path: "requests/file.txt",
        hash: wrongHash,
        type: "request",
        size_bytes: 0,
      },
    ]

    const manifest: EvidenceManifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: entries,
      package_hash: "",
    }
    const hashStr =
      JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
      entries.map((e) => e.hash).join("")
    manifest.package_hash = sha256(hashStr)
    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
  })

  test("Detects package hash mismatch", async () => {
    const pkgId = "pkg-hash-mismatch"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(join(artifactDir, "requests"), { recursive: true })

    const content = "actual content"
    writeFileSync(join(artifactDir, "requests", "f.txt"), content)
    const entryHash = sha256(content)

    const entries: ArtifactEntry[] = [
      {
        path: "requests/f.txt",
        hash: entryHash,
        type: "request",
        size_bytes: content.length,
      },
    ]

    const manifest: EvidenceManifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: entries,
      package_hash: "0000000000000000000000000000000000000000000000000000000000000000",
    }
    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(
      result.errors.some((e: string) => e.includes("Package hash does not match")),
    ).toBe(true)
  })

  test("Returns invalid for package ID with special characters", async () => {
    const result = await verifyPackage(baseDir, "eng-1", "../../../etc/passwd")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Invalid package ID")
  })

  test("Returns invalid for package ID with spaces", async () => {
    const result = await verifyPackage(baseDir, "eng-1", "package with spaces")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Invalid package ID")
  })

  test("Returns invalid for corrupt manifest JSON", async () => {
    const pkgId = "corrupt-manifest"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(artifactDir, { recursive: true })
    writeFileSync(join(artifactDir, "manifest.json"), "{invalid json content")

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Corrupt manifest"))).toBe(true)
  })

  test("Returns valid for a package with empty artifact list", async () => {
    const pkgId = "empty-artifacts"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(artifactDir, { recursive: true })

    const manifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: [],
      package_hash: "",
    }

    const hashStr =
      JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
      ""  // no artifact hashes
    manifest.package_hash = sha256(hashStr)

    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  test("Returns invalid for non-existent engagement directory", async () => {
    const result = await verifyPackage(baseDir, "nonexistent-eng", "any-pkg")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Manifest file not found")
  })

  test("Returns invalid when baseDir does not exist", async () => {
    const result = await verifyPackage("/nonexistent/path", "eng-1", "any-pkg")
    expect(result.valid).toBe(false)
    expect(result.errors).toContain("Manifest file not found")
  })

  test("Detects artifact hash mismatch for deeply nested artifacts", async () => {
    const pkgId = "nested-artifact"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(join(artifactDir, "deeply", "nested", "path"), { recursive: true })

    const wrongContent = "wrong content"
    writeFileSync(join(artifactDir, "deeply", "nested", "path", "result.json"), wrongContent)

    // Use a hash of different content
    const otherContent = "expected content"
    const wrongHashForFile = sha256(otherContent)

    const entries: ArtifactEntry[] = [
      {
        path: "deeply/nested/path/result.json",
        hash: wrongHashForFile,  // wrong hash for the actual content
        type: "response",
        size_bytes: Buffer.byteLength(wrongContent),
      },
    ]

    const manifest: EvidenceManifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: entries,
      package_hash: "",
    }
    const hashStr =
      JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
      entries.map((e) => e.hash).join("")
    manifest.package_hash = sha256(hashStr)
    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
  })

  test("Returns invalid when manifest has artifact entry but file is missing", async () => {
    const pkgId = "missing-file"
    const artifactDir = join(baseDir, "eng-1", "artifacts", pkgId)
    mkdirSync(artifactDir, { recursive: true })

    // Create manifest referencing a file that doesn't exist
    const ghostHash = sha256("ghost content")
    const entries: ArtifactEntry[] = [
      {
        path: "ghost_file.txt",
        hash: ghostHash,
        type: "request",
        size_bytes: 0,
      },
    ]

    const manifest: EvidenceManifest = {
      package_id: pkgId,
      engagement_id: "eng-1",
      created_at: new Date().toISOString(),
      artifacts: entries,
      package_hash: "",
    }
    const hashStr =
      JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
      entries.map((e) => e.hash).join("")
    manifest.package_hash = sha256(hashStr)
    writeFileSync(
      join(artifactDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    const result = await verifyPackage(baseDir, "eng-1", pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Artifact missing"))).toBe(true)
  })
})
