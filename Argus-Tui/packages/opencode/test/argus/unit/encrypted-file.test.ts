/**
 * EncryptedFileHandle — unit tests
 *
 * Tests the full lifecycle: encrypt then write to disk, read then decrypt,
 * integrity verification via verifyPackage, atomic write safety, large files,
 * and error handling for corrupted/tampered files.
 *
 * These tests DO NOT require macOS Keychain — they work with any master key
 * generated in-memory via crypto.randomBytes().
 */
import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync, readFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"
import crypto from "node:crypto"
import { EncryptedFileHandle } from "../../../src/argus/storage/encrypted-file"
import { EncryptionManager } from "../../../src/argus/storage/encryption"
import { verifyPackage } from "../../../src/argus/evidence/integrity"
import type { EvidenceManifest } from "../../../src/argus/evidence/types"

// ── Helpers ──

let tempDir: string
let masterKey: Buffer

beforeAll(() => {
  tempDir = mkdtempSync(join(tmpdir(), "encrypted-file-test-"))
  masterKey = crypto.randomBytes(32)
})

afterAll(() => {
  try { rmSync(tempDir, { recursive: true, force: true }) } catch { /* best-effort */ }
})

function withTempSubDir(name: string): string {
  const dir = join(tempDir, name)
  mkdirSync(dir, { recursive: true })
  return dir
}

// ── Tests ──

describe("EncryptedFileHandle", () => {
  // ── Write/Read roundtrip ──

  test("writeEncrypted / readEncrypted roundtrip (text)", () => {
    const dir = withTempSubDir("roundtrip-text")
    const filePath = join(dir, "artifact.txt")
    const plaintext = Buffer.from("Hello, encrypted evidence!", "utf-8")

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-test", "artifact.txt")
    expect(existsSync(filePath)).toBe(true)

    const decrypted = EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-test", "artifact.txt")
    expect(decrypted.toString()).toBe("Hello, encrypted evidence!")
  })

  test("writeEncrypted / readEncrypted roundtrip (binary/PNG)", () => {
    const dir = withTempSubDir("roundtrip-binary")
    const filePath = join(dir, "screenshot.png")
    const plaintext = crypto.randomBytes(4096) // simulated PNG

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-bin", "screenshots/screenshot.png")
    const decrypted = EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-bin", "screenshots/screenshot.png")
    expect(decrypted).toEqual(plaintext)
  })

  test("writeEncrypted / readEncrypted large file (1 MB)", () => {
    const dir = withTempSubDir("large-file")
    const filePath = join(dir, "large.bin")
    const plaintext = crypto.randomBytes(1024 * 1024) // 1 MB

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-large", "large.bin")
    const decrypted = EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-large", "large.bin")
    expect(decrypted).toEqual(plaintext)
  })

  test("writeEncrypted handles empty buffer", () => {
    const dir = withTempSubDir("empty")
    const filePath = join(dir, "empty.txt")
    const plaintext = Buffer.alloc(0)

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-empty", "empty.txt")
    const decrypted = EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-empty", "empty.txt")
    expect(decrypted.length).toBe(0)
  })

  test("writeEncrypted produces different ciphertext for same plaintext (random salt+IV)", () => {
    const dir = withTempSubDir("nonce")
    const filePath1 = join(dir, "same-content-1.txt")
    const filePath2 = join(dir, "same-content-2.txt")
    const plaintext = Buffer.from("same data", "utf-8")

    EncryptedFileHandle.writeEncrypted(filePath1, plaintext, masterKey, "ENG-nonce", "f1")
    EncryptedFileHandle.writeEncrypted(filePath2, plaintext, masterKey, "ENG-nonce", "f2")

    const raw1 = readFileSync(filePath1)
    const raw2 = readFileSync(filePath2)
    expect(raw1).not.toEqual(raw2) // different salt/IV → different ciphertext
  })

  // ── Wrong key/ID rejection ──

  test("readEncrypted rejects wrong master key", () => {
    const dir = withTempSubDir("wrong-key")
    const filePath = join(dir, "secret.txt")
    const plaintext = Buffer.from("secret data", "utf-8")
    const wrongKey = crypto.randomBytes(32)

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-wrong-key", "secret.txt")
    expect(() => {
      EncryptedFileHandle.readEncrypted(filePath, wrongKey, "ENG-wrong-key", "secret.txt")
    }).toThrow() // GCM auth tag mismatch
  })

  test("readEncrypted rejects wrong engagement ID", () => {
    const dir = withTempSubDir("wrong-eng")
    const filePath = join(dir, "data.txt")
    const plaintext = Buffer.from("engagement-specific data", "utf-8")

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-correct", "data.txt")
    expect(() => {
      EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-wrong", "data.txt")
    }).toThrow() // GCM auth tag mismatch
  })

  test("readEncrypted rejects wrong file ID", () => {
    const dir = withTempSubDir("wrong-fileid")
    const filePath = join(dir, "correct-file.txt")
    const plaintext = Buffer.from("file-specific data", "utf-8")

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-fid", "correct-file.txt")
    expect(() => {
      EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-fid", "wrong-file.txt")
    }).toThrow() // GCM auth tag mismatch
  })

  // ── Tamper detection ──

  test("readEncrypted rejects tampered ciphertext", () => {
    const dir = withTempSubDir("tamper")
    const filePath = join(dir, "tampered.bin")
    const plaintext = Buffer.from("tamper test", "utf-8")

    EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, "ENG-tamper", "tampered.bin")

    // Corrupt a byte in the file
    const raw = readFileSync(filePath)
    raw[raw.length - 1] ^= 0xff
    writeFileSync(filePath, raw)

    expect(() => {
      EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-tamper", "tampered.bin")
    }).toThrow() // GCM auth tag verification fails
  })

  test("readEncrypted rejects corrupt/truncated file", () => {
    const dir = withTempSubDir("corrupt")
    const filePath = join(dir, "corrupt.bin")
    writeFileSync(filePath, Buffer.alloc(5)) // too short

    expect(() => {
      EncryptedFileHandle.readEncrypted(filePath, masterKey, "ENG-corrupt", "corrupt.bin")
    }).toThrow("too short or corrupted")
  })

  // ── File metadata ──

  test("writeEncrypted writes the file atomically (no .encrypting temp left behind)", () => {
    const dir = withTempSubDir("atomic")
    const filePath = join(dir, "atomic.txt")

    EncryptedFileHandle.writeEncrypted(filePath, Buffer.from("atomic write test"), masterKey, "ENG-atomic", "atomic.txt")

    expect(existsSync(filePath)).toBe(true)
    expect(existsSync(filePath + ".encrypting")).toBe(false) // temp should be gone
  })

  test("isEncryptedFile detects encrypted format", () => {
    const dir = withTempSubDir("detect")
    const filePath = join(dir, "encrypted.bin")

    EncryptedFileHandle.writeEncrypted(filePath, Buffer.from("detect me"), masterKey, "ENG-detect", "encrypted.bin")
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)
  })

  test("isEncryptedFile returns false for plaintext files", () => {
    const dir = withTempSubDir("plain")
    const filePath = join(dir, "plain.txt")
    writeFileSync(filePath, "this is plaintext")

    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(false)
  })

  test("isEncryptedFile returns false for empty file", () => {
    const dir = withTempSubDir("empty-file")
    const filePath = join(dir, "empty.txt")
    writeFileSync(filePath, "")

    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(false)
  })

  test("isEncryptedFile returns false for non-existent file", () => {
    expect(EncryptedFileHandle.isEncryptedFile("/nonexistent/file.bin")).toBe(false)
  })

  // ── Delete ──

  test("deleteEncrypted removes the file", () => {
    const dir = withTempSubDir("delete")
    const filePath = join(dir, "delete-me.txt")

    EncryptedFileHandle.writeEncrypted(filePath, Buffer.from("delete me"), masterKey, "ENG-del", "delete-me.txt")
    expect(existsSync(filePath)).toBe(true)

    EncryptedFileHandle.deleteEncrypted(filePath)
    expect(existsSync(filePath)).toBe(false)
  })

  test("deleteEncrypted is idempotent (no error on missing file)", () => {
    expect(() => EncryptedFileHandle.deleteEncrypted("/nonexistent/file.bin")).not.toThrow()
  })

  // ── fileIdFromPath ──

  test("fileIdFromPath normalizes backslashes to forward slashes", () => {
    expect(EncryptedFileHandle.fileIdFromPath("requests\\req.txt")).toBe("requests/req.txt")
  })

  test("fileIdFromPath preserves forward slashes", () => {
    expect(EncryptedFileHandle.fileIdFromPath("screenshots/shot.png")).toBe("screenshots/shot.png")
  })

  test("fileIdFromPath handles simple filenames", () => {
    expect(EncryptedFileHandle.fileIdFromPath("artifact.txt")).toBe("artifact.txt")
  })
})

// ── Integration: verifyPackage with encrypted files ──

describe("verifyPackage with encrypted files", () => {
  test("verifyPackage validates encrypted files when masterKey is provided", async () => {
    const engId = "eng-verify-enc"
    const pkgId = "pkg-enc-1"
    const artifactDir = join(tempDir, engId, "artifacts", pkgId)
    mkdirSync(join(artifactDir, "requests"), { recursive: true })

    // Create an encrypted file
    const reqPath = join(artifactDir, "requests", "req.txt")
    const content = Buffer.from("encrypted request", "utf-8")
    EncryptedFileHandle.writeEncrypted(reqPath, content, masterKey, engId, "requests/req.txt")

    // Create manifest with plaintext hash
    const contentHash = crypto.createHash("sha256").update(content).digest("hex")
    const artifacts = [
      { path: "requests/req.txt", hash: contentHash, type: "request" as const, size_bytes: content.length },
    ]

    // Build manifest with a single created_at timestamp (must be identical
    // between computePackageHash and what's written to disk)
    const { computePackageHash } = await import("../../../src/argus/evidence/hash")
    const createdAt = new Date().toISOString()
    const manifest: Record<string, unknown> = {
      package_id: pkgId,
      engagement_id: engId,
      created_at: createdAt,
      artifacts,
      package_hash: "",
    }
    manifest.package_hash = computePackageHash(
      manifest as unknown as EvidenceManifest,
      artifacts,
    )
    writeFileSync(join(artifactDir, "manifest.json"), JSON.stringify(manifest, null, 2))

    // Verify with masterKey — should succeed
    const result = await verifyPackage(tempDir, engId, pkgId, { masterKey })
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  test("verifyPackage fails for encrypted files without masterKey", async () => {
    const engId = "eng-verify-no-key"
    const pkgId = "pkg-no-key"
    const artifactDir = join(tempDir, engId, "artifacts", pkgId)
    mkdirSync(join(artifactDir, "screenshots"), { recursive: true })

    // Create an encrypted file
    const shotPath = join(artifactDir, "screenshots", "shot.png")
    const content = Buffer.from("encrypted screenshot", "utf-8")
    EncryptedFileHandle.writeEncrypted(shotPath, content, masterKey, engId, "screenshots/shot.png")

    const contentHash = crypto.createHash("sha256").update(content).digest("hex")
    const artifacts = [
      { path: "screenshots/shot.png", hash: contentHash, type: "screenshot" as const, size_bytes: content.length },
    ]

    const { computePackageHash } = await import("../../../src/argus/evidence/hash")
    const manifest = {
      package_id: pkgId,
      engagement_id: engId,
      created_at: new Date().toISOString(),
      artifacts,
      package_hash: computePackageHash(
        { package_id: pkgId, engagement_id: engId, created_at: new Date().toISOString(), artifacts, package_hash: "" },
        artifacts,
      ),
    }
    writeFileSync(join(artifactDir, "manifest.json"), JSON.stringify(manifest, null, 2))

    // Verify WITHOUT masterKey — should fail because encrypted file bytes
    // don't match the plaintext hash
    const result = await verifyPackage(tempDir, engId, pkgId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
  })

  test("verifyPackage handles decryption failure gracefully", async () => {
    const engId = "eng-verify-bad-key"
    const pkgId = "pkg-bad-key"
    const artifactDir = join(tempDir, engId, "artifacts", pkgId)
    mkdirSync(join(artifactDir, "requests"), { recursive: true })

    // Create file with one key, but verify with a different one
    const reqPath = join(artifactDir, "requests", "req.txt")
    const content = Buffer.from("some request data", "utf-8")
    EncryptedFileHandle.writeEncrypted(reqPath, content, masterKey, engId, "requests/req.txt")

    const contentHash = crypto.createHash("sha256").update(content).digest("hex")
    const artifacts = [
      { path: "requests/req.txt", hash: contentHash, type: "request" as const, size_bytes: content.length },
    ]

    const { computePackageHash } = await import("../../../src/argus/evidence/hash")
    const manifest = {
      package_id: pkgId,
      engagement_id: engId,
      created_at: new Date().toISOString(),
      artifacts,
      package_hash: computePackageHash(
        { package_id: pkgId, engagement_id: engId, created_at: new Date().toISOString(), artifacts, package_hash: "" },
        artifacts,
      ),
    }
    writeFileSync(join(artifactDir, "manifest.json"), JSON.stringify(manifest, null, 2))

    // Verify with WRONG master key — should report decryption failure
    const wrongKey = crypto.randomBytes(32)
    const result = await verifyPackage(tempDir, engId, pkgId, { masterKey: wrongKey })
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Failed to decrypt"))).toBe(true)
  })
})
