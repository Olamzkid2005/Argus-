import { describe, it, expect, mock, beforeEach } from "bun:test"
import { createHash } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "../../../../src/argus/evidence/types"

const mockReadFile = mock<(path: string, encoding?: string) => Promise<string>>()
const mockReaddir = mock<(path: string, opts?: any) => Promise<any[]>>()
const mockWriteFile = mock<(path: string, data: string) => Promise<void>>()
const mockMkdir = mock<(path: string, opts?: any) => Promise<void>>()
const mockStat = mock<(path: string) => Promise<{ size: number }>>()
const mockRm = mock<(path: string, opts?: any) => Promise<void>>()
const mockExistsSync = mock<(path: string) => boolean>()

mock.module("fs/promises", () => ({
  readFile: mockReadFile,
  readdir: mockReaddir,
  writeFile: mockWriteFile,
  mkdir: mockMkdir,
  stat: mockStat,
  rm: mockRm,
}))

mock.module("fs", () => ({
  existsSync: mockExistsSync,
}))

const { ArtifactStore } = await import("../../../../src/argus/evidence/store")

describe("ArtifactStore", () => {
  beforeEach(() => {
    mockReadFile.mockReset()
    mockReaddir.mockReset()
    mockWriteFile.mockReset()
    mockMkdir.mockReset()
    mockStat.mockReset()
    mockRm.mockReset()
    mockExistsSync.mockReset()
  })

  describe("createPackage", () => {
    it("rejects invalid engagementId", async () => {
      const store = new ArtifactStore("/base")
      await expect(store.createPackage("", "find-1", [])).rejects.toThrow("Invalid engagementId")
    })

    it("rejects invalid findingId", async () => {
      const store = new ArtifactStore("/base")
      await expect(store.createPackage("eng-1", "", [])).rejects.toThrow("Invalid findingId")
    })

    it("creates directory and writes manifest.json", async () => {
      const store = new ArtifactStore("/base")
      const artifacts: ArtifactEntry[] = [
        { path: "requests/req.txt", hash: "abc", type: "request", size_bytes: 10 },
      ]
      mockMkdir.mockResolvedValue(undefined)
      mockWriteFile.mockResolvedValue(undefined)

      const manifest = await store.createPackage("eng-1", "find-1", artifacts)

      expect(mockMkdir).toHaveBeenCalledWith("/base/eng-1/artifacts/find-1", { recursive: true })
      expect(mockWriteFile).toHaveBeenCalledTimes(1)
      expect(mockWriteFile.mock.calls[0][0]).toBe("/base/eng-1/artifacts/find-1/manifest.json")

      const written = JSON.parse(mockWriteFile.mock.calls[0][1])
      expect(written.package_id).toBe("find-1")
      expect(written.engagement_id).toBe("eng-1")
      expect(written.artifacts).toEqual(artifacts)
      expect(written.package_hash).toBeTruthy()
      expect(typeof written.package_hash).toBe("string")
    })

    it("computes package_hash from manifest + artifact hashes", async () => {
      const store = new ArtifactStore("/base")
      const artifacts: ArtifactEntry[] = [
        { path: "requests/req.txt", hash: "abc", type: "request", size_bytes: 4 },
        { path: "responses/res.txt", hash: "def", type: "response", size_bytes: 5 },
      ]
      mockMkdir.mockResolvedValue(undefined)
      mockWriteFile.mockResolvedValue(undefined)

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
    })
  })

  describe("getPackage", () => {
    it("returns manifest when file exists", async () => {
      const store = new ArtifactStore("/base")
      const manifestData: EvidenceManifest = {
        package_id: "find-1",
        engagement_id: "eng-1",
        created_at: "2024-01-01T00:00:00.000Z",
        artifacts: [],
        package_hash: "hash123",
      }
      mockExistsSync.mockReturnValue(true)
      mockReadFile.mockResolvedValue(JSON.stringify(manifestData))

      const result = await store.getPackage("eng-1", "find-1")

      expect(result).toEqual(manifestData)
      expect(mockExistsSync).toHaveBeenCalledWith(
        "/base/eng-1/artifacts/find-1/manifest.json",
      )
      expect(mockReadFile).toHaveBeenCalledWith(
        "/base/eng-1/artifacts/find-1/manifest.json",
        "utf-8",
      )
    })

    it("returns null when manifest doesn't exist", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(false)

      const result = await store.getPackage("eng-1", "find-1")

      expect(result).toBeNull()
      expect(mockReadFile).not.toHaveBeenCalled()
    })
  })

  describe("listPackages", () => {
    it("returns manifests for each subdirectory", async () => {
      const store = new ArtifactStore("/base")
      const manifest1: EvidenceManifest = {
        package_id: "find-1", engagement_id: "eng-1", created_at: "", artifacts: [], package_hash: "",
      }
      const manifest2: EvidenceManifest = {
        package_id: "find-2", engagement_id: "eng-1", created_at: "", artifacts: [], package_hash: "",
      }
      mockExistsSync.mockReturnValue(true)
      mockReaddir.mockResolvedValue([
        { name: "find-1", isDirectory: () => true },
        { name: "find-2", isDirectory: () => true },
        { name: "not-a-dir", isDirectory: () => false },
      ])
      mockReadFile
        .mockResolvedValueOnce(JSON.stringify(manifest1))
        .mockResolvedValueOnce(JSON.stringify(manifest2))

      const result = await store.listPackages("eng-1")

      expect(result).toHaveLength(2)
      expect(result[0]).toEqual(manifest1)
      expect(result[1]).toEqual(manifest2)
      expect(mockExistsSync).toHaveBeenCalledWith("/base/eng-1/artifacts")
    })

    it("returns empty when artifacts dir doesn't exist", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(false)

      const result = await store.listPackages("eng-1")

      expect(result).toHaveLength(0)
      expect(mockReaddir).not.toHaveBeenCalled()
    })
  })

  describe("deletePackage", () => {
    it("removes directory recursively", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(true)
      mockRm.mockResolvedValue(undefined)

      const result = await store.deletePackage("eng-1", "find-1")

      expect(result).toBe(true)
      expect(mockRm).toHaveBeenCalledWith("/base/eng-1/artifacts/find-1", {
        recursive: true,
        force: true,
      })
    })

    it("returns false when directory doesn't exist", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(false)

      const result = await store.deletePackage("eng-1", "find-1")

      expect(result).toBe(false)
      expect(mockRm).not.toHaveBeenCalled()
    })
  })

  describe("getEngagementSize", () => {
    it("returns total size of all files", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(true)
      mockReaddir.mockResolvedValue([
        { name: "file-a.txt", isFile: () => true, parentPath: "/base/eng-1/artifacts/find-1" },
        { name: "file-b.txt", isFile: () => true, parentPath: "/base/eng-1/artifacts/find-1" },
        { name: "subdir", isFile: () => false, parentPath: "/base/eng-1/artifacts" },
      ])
      mockStat
        .mockResolvedValueOnce({ size: 100 })
        .mockResolvedValueOnce({ size: 200 })

      const result = await store.getEngagementSize("eng-1")

      expect(result).toBe(300)
      expect(mockStat).toHaveBeenCalledTimes(2)
    })

    it("returns 0 when dir doesn't exist", async () => {
      const store = new ArtifactStore("/base")
      mockExistsSync.mockReturnValue(false)

      const result = await store.getEngagementSize("eng-1")

      expect(result).toBe(0)
      expect(mockReaddir).not.toHaveBeenCalled()
    })
  })
})
