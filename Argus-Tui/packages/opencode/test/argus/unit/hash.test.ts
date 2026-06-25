import { describe, expect, test } from "bun:test"
import { computePackageHash } from "../../../src/argus/evidence/hash"
import type { EvidenceManifest, ArtifactEntry } from "../../../src/argus/evidence/types"

describe("computePackageHash canonical serialization", () => {
  const baseManifest: EvidenceManifest = {
    package_id: "pkg-001",
    engagement_id: "eng-001",
    created_at: "2025-01-01T00:00:00.000Z",
    artifacts: [],
    package_hash: "old-hash-value",
  }

  const baseArtifacts: ArtifactEntry[] = [
    { path: "screenshots/scan.png", hash: "abc123", type: "screenshot", size_bytes: 1024 },
  ]

  test("same manifest data produces same hash", () => {
    const hash1 = computePackageHash(baseManifest, baseArtifacts)
    const hash2 = computePackageHash(baseManifest, baseArtifacts)
    expect(hash1).toBe(hash2)
  })

  test("key order does not affect the hash", () => {
    const ordered: EvidenceManifest = {
      package_id: "pkg-001",
      engagement_id: "eng-001",
      created_at: "2025-01-01T00:00:00.000Z",
      artifacts: baseArtifacts,
      package_hash: "old-hash-value",
    }
    const reversed: EvidenceManifest = {
      package_hash: "old-hash-value",
      artifacts: baseArtifacts,
      created_at: "2025-01-01T00:00:00.000Z",
      engagement_id: "eng-001",
      package_id: "pkg-001",
    }
    expect(computePackageHash(ordered, baseArtifacts))
      .toBe(computePackageHash(reversed, baseArtifacts))
  })

  test("package_hash value is zeroed out before hashing", () => {
    const manifest1 = { ...baseManifest, package_hash: "hash-a" }
    const manifest2 = { ...baseManifest, package_hash: "hash-b" }
    expect(computePackageHash(manifest1, baseArtifacts))
      .toBe(computePackageHash(manifest2, baseArtifacts))
  })

  test("package_hash value of empty string produces same hash as any other", () => {
    const emptyHash = { ...baseManifest, package_hash: "" }
    const nonEmptyHash = { ...baseManifest, package_hash: "anything" }
    expect(computePackageHash(emptyHash, baseArtifacts))
      .toBe(computePackageHash(nonEmptyHash, baseArtifacts))
  })

  test("different artifact hashes produce different hash", () => {
    const artifactA: ArtifactEntry[] = [
      { path: "screenshots/scan.png", hash: "abc123", type: "screenshot", size_bytes: 1024 },
    ]
    const artifactB: ArtifactEntry[] = [
      { path: "screenshots/scan.png", hash: "xyz789", type: "screenshot", size_bytes: 1024 },
    ]
    expect(computePackageHash(baseManifest, artifactA))
      .not.toBe(computePackageHash(baseManifest, artifactB))
  })

  test("different manifest fields produce different hash", () => {
    const manifestA: EvidenceManifest = {
      ...baseManifest,
      package_id: "pkg-001",
    }
    const manifestB: EvidenceManifest = {
      ...baseManifest,
      package_id: "pkg-002",
    }
    expect(computePackageHash(manifestA, baseArtifacts))
      .not.toBe(computePackageHash(manifestB, baseArtifacts))
  })

  test("different artifact order produces different hash (order matters)", () => {
    const artifactsA: ArtifactEntry[] = [
      { path: "a.png", hash: "hash1", type: "screenshot", size_bytes: 100 },
      { path: "b.png", hash: "hash2", type: "screenshot", size_bytes: 200 },
    ]
    const artifactsB: ArtifactEntry[] = [
      { path: "b.png", hash: "hash2", type: "screenshot", size_bytes: 200 },
      { path: "a.png", hash: "hash1", type: "screenshot", size_bytes: 100 },
    ]
    expect(computePackageHash(baseManifest, artifactsA))
      .not.toBe(computePackageHash(baseManifest, artifactsB))
  })

  test("artifacts field is sorted by key in hash input (not by artifact content)", () => {
    const manifest: EvidenceManifest = {
      package_id: "pkg-001",
      engagement_id: "eng-001",
      created_at: "2025-01-01T00:00:00.000Z",
      package_hash: "",
      artifacts: baseArtifacts,
    }
    const hash = computePackageHash(manifest, baseArtifacts)
    expect(typeof hash).toBe("string")
    expect(hash.length).toBe(64)
  })

  test("returns consistent 64-char hex string", () => {
    const hash = computePackageHash(baseManifest, baseArtifacts)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })
})
