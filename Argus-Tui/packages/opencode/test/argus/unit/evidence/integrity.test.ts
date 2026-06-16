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
): string {
  const artifactDir = join(baseDir, "artifacts", packageId)
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
  test("Returns invalid with error when manifest file not found", () => {
    const result = verifyPackage(baseDir, "nonexistent")
    expect(result.valid).toBe(false)
    expect(result.packageId).toBe("nonexistent")
    expect(result.errors).toContain("Manifest file not found")
  })

  test("Returns valid for a package with all artifacts present and matching hashes", () => {
    const pkgId = setupPackage("valid-pkg", [
      { path: "requests/req.txt", content: "request data" },
      { path: "responses/res.txt", content: "response data" },
    ])
    const result = verifyPackage(baseDir, pkgId)
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
    expect(result.packageId).toBe(pkgId)
    expect(result.manifestHash).toBeTruthy()
    expect(result.computedHash).toBe(result.manifestHash)
  })

  test("Detects missing artifacts", () => {
    const pkgId = "missing-artifact"
    const artifactDir = join(baseDir, "artifacts", pkgId)
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

    const result = verifyPackage(baseDir, pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.includes("Artifact missing"))).toBe(true)
  })

  test("Detects hash mismatches", () => {
    const pkgId = "hash-mismatch"
    const artifactDir = join(baseDir, "artifacts", pkgId)
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

    const result = verifyPackage(baseDir, pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e) => e.includes("Hash mismatch"))).toBe(true)
  })

  test("Detects package hash mismatch", () => {
    const pkgId = "pkg-hash-mismatch"
    const artifactDir = join(baseDir, "artifacts", pkgId)
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

    const result = verifyPackage(baseDir, pkgId)
    expect(result.valid).toBe(false)
    expect(
      result.errors.some((e) => e.includes("Package hash does not match")),
    ).toBe(true)
  })
})
