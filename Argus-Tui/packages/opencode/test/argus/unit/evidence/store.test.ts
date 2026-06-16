import { describe, it, expect } from "bun:test"
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, existsSync, readFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { createHash } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "../../../../src/argus/evidence/types"

const { ArtifactStore } = await import("../../../../src/argus/evidence/store")

function sha256(content: string): string {
  return createHash("sha256").update(content).digest("hex")
}

function withTempDir(fn: (baseDir: string) => Promise<void>): () => Promise<void> {
  return async () => {
    const baseDir = mkdtempSync(join(tmpdir(), "artifact-store-test-"))
    try {
      await fn(baseDir)
    } finally {
      try { rmSync(baseDir, { recursive: true, force: true }) } catch {}
    }
  }
}

describe("ArtifactStore", () => {
  describe("createPackage", () => {
    it("rejects invalid engagementId", async () => {
      const store = new ArtifactStore("/tmp")
      await expect(store.createPackage("", "find-1", [])).rejects.toThrow("Invalid engagementId")
    })

    it("rejects invalid findingId", async () => {
      const store = new ArtifactStore("/tmp")
      await expect(store.createPackage("eng-1", "", [])).rejects.toThrow("Invalid findingId")
    })

    it("creates directory and writes manifest.json", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const artifacts: ArtifactEntry[] = [
        { path: "requests/req.txt", hash: "abc", type: "request", size_bytes: 10 },
      ]
      const manifest = await store.createPackage("eng-1", "find-1", artifacts)

      const manifestPath = join(baseDir, "eng-1", "artifacts", "find-1", "manifest.json")
      expect(existsSync(manifestPath)).toBe(true)
      const written = JSON.parse(readFileSync(manifestPath, "utf-8"))
      expect(written.package_id).toBe("find-1")
      expect(written.engagement_id).toBe("eng-1")
      expect(written.artifacts).toEqual(artifacts)
      expect(written.package_hash).toBeTruthy()
      expect(typeof written.package_hash).toBe("string")
    }))

    it("computes package_hash from manifest + artifact hashes", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const artifacts: ArtifactEntry[] = [
        { path: "requests/req.txt", hash: "abc", type: "request", size_bytes: 4 },
        { path: "responses/res.txt", hash: "def", type: "response", size_bytes: 5 },
      ]
      const manifest = await store.createPackage("eng-1", "find-2", artifacts)

      const expectedStr =
        JSON.stringify(
          {
            package_id: "find-2",
            engagement_id: "eng-1",
            created_at: manifest.created_at,
            artifacts,
            package_hash: "",
          },
          null,
          2,
        ) + "abcdef"
      const expectedHash = createHash("sha256").update(expectedStr).digest("hex")

      expect(manifest.package_hash).toBe(expectedHash)
    }))
  })

  describe("getPackage", () => {
    it("returns manifest when file exists", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const manifestData: EvidenceManifest = {
        package_id: "find-1",
        engagement_id: "eng-1",
        created_at: "2024-01-01T00:00:00.000Z",
        artifacts: [],
        package_hash: "hash123",
      }
      const pkgDir = join(baseDir, "eng-1", "artifacts", "find-1")
      mkdirSync(pkgDir, { recursive: true })
      writeFileSync(join(pkgDir, "manifest.json"), JSON.stringify(manifestData))

      const result = await store.getPackage("eng-1", "find-1")

      expect(result).toEqual(manifestData)
    }))

    it("returns null when manifest doesn't exist", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const result = await store.getPackage("eng-1", "find-1")
      expect(result).toBeNull()
    }))
  })

  describe("listPackages", () => {
    it("returns manifests for each subdirectory", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const manifest1: EvidenceManifest = {
        package_id: "find-1", engagement_id: "eng-1", created_at: "", artifacts: [], package_hash: "",
      }
      const manifest2: EvidenceManifest = {
        package_id: "find-2", engagement_id: "eng-1", created_at: "", artifacts: [], package_hash: "",
      }

      const artifactsDir = join(baseDir, "eng-1", "artifacts")
      mkdirSync(join(artifactsDir, "find-1"), { recursive: true })
      mkdirSync(join(artifactsDir, "find-2"), { recursive: true })
      writeFileSync(join(artifactsDir, "find-1", "manifest.json"), JSON.stringify(manifest1))
      writeFileSync(join(artifactsDir, "find-2", "manifest.json"), JSON.stringify(manifest2))
      writeFileSync(join(artifactsDir, "not-a-dir.txt"), "this is a file not a directory")

      const result = await store.listPackages("eng-1")

      expect(result).toHaveLength(2)
    }))

    it("returns empty when dir doesn't exist", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const result = await store.listPackages("eng-1")
      expect(result).toHaveLength(0)
    }))
  })

  describe("deletePackage", () => {
    it("removes directory recursively", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const pkgDir = join(baseDir, "eng-1", "artifacts", "find-1")
      mkdirSync(pkgDir, { recursive: true })
      writeFileSync(join(pkgDir, "manifest.json"), "{}")

      const result = await store.deletePackage("eng-1", "find-1")

      expect(result).toBe(true)
      expect(existsSync(pkgDir)).toBe(false)
    }))

    it("returns false when directory doesn't exist", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const result = await store.deletePackage("eng-1", "find-1")
      expect(result).toBe(false)
    }))
  })

  describe("getEngagementSize", () => {
    it("returns total size of all files", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const artifactsDir = join(baseDir, "eng-1", "artifacts")
      mkdirSync(join(artifactsDir, "find-1"), { recursive: true })
      writeFileSync(join(artifactsDir, "find-1", "file-a.txt"), "a".repeat(100))
      writeFileSync(join(artifactsDir, "find-1", "file-b.txt"), "b".repeat(200))

      const result = await store.getEngagementSize("eng-1")

      expect(result).toBe(300)
    }))

    it("returns 0 when dir doesn't exist", withTempDir(async (baseDir) => {
      const store = new ArtifactStore(baseDir)
      const result = await store.getEngagementSize("eng-1")
      expect(result).toBe(0)
    }))
  })
})
