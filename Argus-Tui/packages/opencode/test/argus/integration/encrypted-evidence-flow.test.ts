/**
 * Encrypted Evidence Flow — integration tests
 *
 * Tests the full integration between EvidenceCollector, EncryptedFileHandle,
 * EncryptionManager, and verifyPackage — verifying that evidence artifacts
 * are encrypted at rest, decrypted correctly for integrity verification,
 * and that all artifact types (request, response, screenshot) are handled.
 *
 * This test works on ALL platforms (macOS Keychain + Linux file-based fallback).
 *
 * Integration path:
 *   EvidenceCollector.saveRequest/saveResponse/captureScreenshot
 *     → EncryptedFileHandle.writeEncrypted (via _isEncrypted check)
 *       → EncryptionManager.encryptFile (AES-256-GCM per-file key)
 *   verifyPackage
 *     → EncryptedFileHandle.readEncrypted (when masterKey provided)
 *       → EncryptionManager.decryptFile (AES-256-GCM per-file key)
 */
import { beforeAll, afterAll, describe, expect, test } from "bun:test"
import { readFileSync, existsSync, writeFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import crypto from "node:crypto"

import { EvidenceCollector } from "../../../src/argus/evidence/collector"
import { EncryptedFileHandle } from "../../../src/argus/storage/encrypted-file"
import { EncryptionManager } from "../../../src/argus/storage/encryption"
import { verifyPackage } from "../../../src/argus/evidence/integrity"
import type { EvidenceManifest } from "../../../src/argus/evidence/types"
import {
  makeTempDir,
  cleanupTempDir,
  initEncryptionManager,
  destroyEncryptionManager,
  sha256,
} from "../../argus/helpers/encryption-test-utils"

// ── Helpers ──

let tempDir: string
let masterKey: Buffer

beforeAll(async () => {
  tempDir = makeTempDir("argus-enc-evidence-int-")
  masterKey = await initEncryptionManager()
})

afterAll(async () => {
  await destroyEncryptionManager()
  cleanupTempDir(tempDir)
})

// ═══════════════════════════════════════════════
// 1. Encrypted artifact writes via EvidenceCollector
// ═══════════════════════════════════════════════

describe("Encrypted artifact writes via EvidenceCollector", () => {
  const engId = "ENG-enc-ev-001"
  const findingId = "find-enc-ev-001"
  let collector: EvidenceCollector

  beforeAll(async () => {
    await EncryptionManager.requireMasterKey()
    collector = new EvidenceCollector(tempDir, undefined, engId)
  })

  test("saveRequest writes encrypted file when encryption is enabled", async () => {
    const entry = await collector.saveRequest(engId, findingId, "GET /api/secret HTTP/1.1")
    expect(entry.type).toBe("request")

    const filePath = join(tempDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)

    // File on disk should be encrypted — not plaintext
    const diskBytes = readFileSync(filePath)
    const plaintext = "GET /api/secret HTTP/1.1"
    expect(diskBytes.toString()).not.toContain(plaintext)

    // Should be detected as encrypted format
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)

    // Read back via EncryptedFileHandle should return original plaintext
    const decrypted = EncryptedFileHandle.readEncrypted(
      filePath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(entry.path),
    )
    expect(decrypted.toString()).toBe(plaintext)
  })

  test("saveResponse writes encrypted file when encryption is enabled", async () => {
    const responseBody = JSON.stringify({ status: 200, secret: "classified" })
    const entry = await collector.saveResponse(engId, findingId, responseBody)
    expect(entry.type).toBe("response")

    const filePath = join(tempDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)

    // Encrypted on disk
    const diskBytes = readFileSync(filePath)
    expect(diskBytes.toString()).not.toContain("classified")
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)

    // Decrypt and verify
    const decrypted = EncryptedFileHandle.readEncrypted(
      filePath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(entry.path),
    )
    expect(decrypted.toString()).toBe(responseBody)
  })

  test("captureScreenshot writes encrypted binary file", async () => {
    const screenshotBuf = crypto.randomBytes(8192) // simulated PNG
    const entry = await collector.captureScreenshot(engId, findingId, screenshotBuf)
    expect(entry.type).toBe("screenshot")

    const filePath = join(tempDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)

    // Encrypted on disk
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)

    // Decrypt and verify binary data
    const decrypted = EncryptedFileHandle.readEncrypted(
      filePath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(entry.path),
    )
    expect(decrypted).toEqual(screenshotBuf)
  })

  test("no .encrypting temp files left behind after encrypted writes", async () => {
    // Already written above — verify no temp files remain
    const artifactsDir = join(tempDir, engId, "artifacts", findingId)
    const findTemp = (dir: string): string[] => {
      const results: string[] = []
      try {
        const walk = (d: string) => {
          for (const entry of readdirSync(d, { withFileTypes: true })) {
            const full = join(d, entry.name)
            if (entry.isDirectory()) walk(full)
            else if (entry.name.endsWith(".encrypting")) results.push(full)
          }
        }
        walk(dir)
      } catch { /* dir may not exist */ }
      return results
    }

    const temps = findTemp(artifactsDir)
    expect(temps).toHaveLength(0)
  })
})

// ═══════════════════════════════════════════════
// 2. Manifest hash integrity
// ═══════════════════════════════════════════════

describe("Manifest hash integrity with encrypted artifacts", () => {
  const engId = "ENG-enc-manifest-001"
  const findingId = "find-enc-manifest-001"
  let collector: EvidenceCollector

  beforeAll(async () => {
    await EncryptionManager.requireMasterKey()
    collector = new EvidenceCollector(tempDir, undefined, engId)
  })

  test("manifest hash is computed on plaintext, not ciphertext", async () => {
    const req = await collector.saveRequest(engId, findingId, "POST /api/data HTTP/1.1")
    const res = await collector.saveResponse(engId, findingId, '{"result":"ok"}')
    const manifest = await collector.createPackage(engId, findingId, [req, res])

    expect(manifest.artifacts).toHaveLength(2)

    // The hash in the manifest should match the PLAINTEXT hash
    const reqPlaintext = "POST /api/data HTTP/1.1"
    expect(req.hash).toBe(sha256(reqPlaintext))

    const resPlaintext = '{"result":"ok"}'
    expect(res.hash).toBe(sha256(resPlaintext))

    // The ciphertext hash should be different from the plaintext hash
    const reqPath = join(tempDir, engId, "artifacts", findingId, req.path)
    const ciphertext = readFileSync(reqPath)
    expect(sha256(ciphertext)).not.toBe(req.hash)
  })

  test("package_hash is valid after creation", async () => {
    // Re-verify using computePackageHash
    const { computePackageHash } = await import("../../../src/argus/evidence/hash")
    const manifestPath = join(tempDir, engId, "artifacts", findingId, "manifest.json")
    const diskManifest = JSON.parse(readFileSync(manifestPath, "utf-8")) as EvidenceManifest
    const computed = computePackageHash(diskManifest, diskManifest.artifacts)
    expect(computed).toBe(diskManifest.package_hash)
  })
})

// ═══════════════════════════════════════════════
// 3. verifyPackage with encrypted artifacts
// ═══════════════════════════════════════════════

describe("verifyPackage with encrypted artifacts", () => {
  const engId = "ENG-enc-verify-001"
  const findingId = "find-enc-verify-001"

  beforeAll(async () => {
    await EncryptionManager.requireMasterKey()
    const collector = new EvidenceCollector(tempDir, undefined, engId)

    const req = await collector.saveRequest(engId, findingId, "GET /verify-enc HTTP/1.1")
    const res = await collector.saveResponse(engId, findingId, '{"verified":true}')
    const shot = await collector.captureScreenshot(engId, findingId, crypto.randomBytes(1024))
    await collector.createPackage(engId, findingId, [req, res, shot])
  })

  test("verifyPackage passes with correct masterKey", async () => {
    const result = await verifyPackage(tempDir, engId, findingId, { masterKey })
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
    expect(result.packageId).toBe(findingId)
  })

  test("verifyPackage fails without masterKey (hash mismatch on encrypted bytes)", async () => {
    const result = await verifyPackage(tempDir, engId, findingId)
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
  })

  test("verifyPackage fails with wrong masterKey (decryption failure)", async () => {
    const wrongKey = crypto.randomBytes(32)
    const result = await verifyPackage(tempDir, engId, findingId, { masterKey: wrongKey })
    expect(result.valid).toBe(false)
    expect(result.errors.some((e: string) => e.includes("Failed to decrypt"))).toBe(true)
  })

  test("verifyPackage detects tampered encrypted artifact", async () => {
    // Tamper with one encrypted file
    const artifactsDir = join(tempDir, engId, "artifacts", findingId)
    const screenshotDir = join(artifactsDir, "screenshots")
    let files: string[] = []
    try { files = readdirSync(screenshotDir) } catch { /* no screenshots dir */ }
    if (files.length > 0) {
      const tamperPath = join(screenshotDir, files[0])
      const raw = readFileSync(tamperPath)
      raw[raw.length - 1] ^= 0xff // corrupt last byte
      writeFileSync(tamperPath, raw)

      const result = await verifyPackage(tempDir, engId, findingId, { masterKey })
      expect(result.valid).toBe(false)
      expect(result.errors.some((e: string) => e.includes("Failed to decrypt") || e.includes("Hash mismatch"))).toBe(true)
    }
  })
})

// ═══════════════════════════════════════════════
// 4. Mixed encrypted + plaintext artifacts
// ═══════════════════════════════════════════════

describe("Mixed encrypted and plaintext artifacts", () => {
  const engId = "ENG-enc-mixed-001"
  const findingId = "find-enc-mixed-001"

  test("multiple encrypted artifacts in one package all verify", async () => {
    await EncryptionManager.requireMasterKey()
    const collector = new EvidenceCollector(tempDir, undefined, engId)

    // Save 5 different artifacts
    const artifacts = []
    for (let i = 0; i < 3; i++) {
      artifacts.push(await collector.saveRequest(engId, findingId, `Request ${i} data`))
    }
    for (let i = 0; i < 2; i++) {
      artifacts.push(await collector.captureScreenshot(engId, findingId, crypto.randomBytes(512)))
    }
    await collector.createPackage(engId, findingId, artifacts)

    // Verify the package
    const result = await verifyPackage(tempDir, engId, findingId, { masterKey })
    expect(result.valid).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  test("encrypted and plaintext artifacts coexist in different engagements", async () => {
    // Plaintext engagement
    const plainEngId = "ENG-plain-001"
    const plainFindingId = "find-plain-001"
    const plainCollector = new EvidenceCollector(tempDir) // no encryptionEngagementId

    const plainReq = await plainCollector.saveRequest(plainEngId, plainFindingId, "plaintext request")
    const plainRes = await plainCollector.saveResponse(plainEngId, plainFindingId, "plaintext response")
    await plainCollector.createPackage(plainEngId, plainFindingId, [plainReq, plainRes])

    // Verify plaintext files are NOT encrypted
    const plainReqPath = join(tempDir, plainEngId, "artifacts", plainFindingId, plainReq.path)
    expect(EncryptedFileHandle.isEncryptedFile(plainReqPath)).toBe(false)
    expect(readFileSync(plainReqPath, "utf-8")).toBe("plaintext request")

    // Verify plaintext package (without masterKey)
    const plainResult = await verifyPackage(tempDir, plainEngId, plainFindingId)
    expect(plainResult.valid).toBe(true)

    // Encrypted engagement (same base dir)
    const encEngId = "ENG-enc-coexist-001"
    const encFindingId = "find-enc-coexist-001"
    await EncryptionManager.requireMasterKey()
    const encCollector = new EvidenceCollector(tempDir, undefined, encEngId)

    const encReq = await encCollector.saveRequest(encEngId, encFindingId, "encrypted request")
    await encCollector.createPackage(encEngId, encFindingId, [encReq])

    // Verify encrypted file IS encrypted
    const encReqPath = join(tempDir, encEngId, "artifacts", encFindingId, encReq.path)
    expect(EncryptedFileHandle.isEncryptedFile(encReqPath)).toBe(true)

    // Verify plaintext package still valid after encrypted one was created
    const plainResult2 = await verifyPackage(tempDir, plainEngId, plainFindingId)
    expect(plainResult2.valid).toBe(true)

    // Verify encrypted package with key
    const encResult = await verifyPackage(tempDir, encEngId, encFindingId, { masterKey })
    expect(encResult.valid).toBe(true)

    // Verify encrypted package WITHOUT key fails
    const encResultNoKey = await verifyPackage(tempDir, encEngId, encFindingId)
    expect(encResultNoKey.valid).toBe(false)
  })
})

// ═══════════════════════════════════════════════
// 5. Multiple findings with encrypted evidence
// ═══════════════════════════════════════════════

describe("Multiple findings with encrypted evidence", () => {
  const engId = "ENG-enc-multi-find-001"

  test("multiple findings each have independently encrypted packages", async () => {
    await EncryptionManager.requireMasterKey()
    const collector = new EvidenceCollector(tempDir, undefined, engId)

    const findingIds = ["find-enc-mf-001", "find-enc-mf-002", "find-enc-mf-003"]

    for (const fid of findingIds) {
      const req = await collector.saveRequest(engId, fid, `Request for ${fid}`)
      const res = await collector.saveResponse(engId, fid, `Response for ${fid}`)
      await collector.createPackage(engId, fid, [req, res])
    }

    // Verify each package independently
    for (const fid of findingIds) {
      const result = await verifyPackage(tempDir, engId, fid, { masterKey })
      expect(result.valid).toBe(true)
      expect(result.errors).toHaveLength(0)
      expect(result.packageId).toBe(fid)

      // Each file should be encrypted
      const reqPath = join(tempDir, engId, "artifacts", fid, "requests")
      let files: string[] = []
      try { files = readdirSync(reqPath) } catch { /* no requests dir */ }
      for (const file of files) {
        expect(EncryptedFileHandle.isEncryptedFile(join(reqPath, file))).toBe(true)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 6. EvidenceCollector encryption toggle
// ═══════════════════════════════════════════════

describe("EvidenceCollector encryption toggle", () => {
  const engId = "ENG-enc-toggle-001"
  const findingId = "find-enc-toggle-001"

  test("setEncryption enables encryption mid-lifecycle", async () => {
    await EncryptionManager.requireMasterKey()
    const collector = new EvidenceCollector(tempDir)

    // Initially no encryption
    const plainReq = await collector.saveRequest(engId, findingId, "before encryption")
    const plainReqPath = join(tempDir, engId, "artifacts", findingId, plainReq.path)
    expect(EncryptedFileHandle.isEncryptedFile(plainReqPath)).toBe(false)

    // Enable encryption
    collector.setEncryption(engId)
    const encReq = await collector.saveRequest(engId, findingId, "after encryption")
    const encReqPath = join(tempDir, engId, "artifacts", findingId, encReq.path)
    expect(EncryptedFileHandle.isEncryptedFile(encReqPath)).toBe(true)

    // Decrypt and verify the encrypted request
    const decrypted = EncryptedFileHandle.readEncrypted(
      encReqPath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(encReq.path),
    )
    expect(decrypted.toString()).toBe("after encryption")

    // Create package with the encrypted artifact only
    await collector.createPackage(engId, findingId, [encReq])

    // Verify encrypted package decrypts correctly
    const result = await verifyPackage(tempDir, engId, findingId, { masterKey })
    expect(result.valid).toBe(true)
  })
})

// ═══════════════════════════════════════════════
// 7. Edge cases
// ═══════════════════════════════════════════════

describe("Edge cases", () => {
  test("empty buffer evidence is encrypted and decrypts correctly", async () => {
    await EncryptionManager.requireMasterKey()
    const engId = "ENG-enc-edge-001"
    const findingId = "find-enc-edge-001"
    const collector = new EvidenceCollector(tempDir, undefined, engId)

    const entry = await collector.saveResponse(engId, findingId, "")
    const filePath = join(tempDir, engId, "artifacts", findingId, entry.path)
    expect(existsSync(filePath)).toBe(true)
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)

    const decrypted = EncryptedFileHandle.readEncrypted(
      filePath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(entry.path),
    )
    expect(decrypted.length).toBe(0)
  })

  test("large payload (100KB) roundtrips through encrypted evidence path", async () => {
    await EncryptionManager.requireMasterKey()
    const engId = "ENG-enc-large-001"
    const findingId = "find-enc-large-001"
    const collector = new EvidenceCollector(tempDir, undefined, engId)

    const largeData = crypto.randomBytes(100 * 1024) // 100KB
    const entry = await collector.captureScreenshot(engId, findingId, largeData)

    const filePath = join(tempDir, engId, "artifacts", findingId, entry.path)
    const decrypted = EncryptedFileHandle.readEncrypted(
      filePath, masterKey, engId,
      EncryptedFileHandle.fileIdFromPath(entry.path),
    )
    expect(decrypted).toEqual(largeData)

    // Verify package
    await collector.createPackage(engId, findingId, [entry])
    const result = await verifyPackage(tempDir, engId, findingId, { masterKey })
    expect(result.valid).toBe(true)
  })

  test("collector without encryption enabled stores plaintext", async () => {
    const engId = "ENG-plain-only-001"
    const findingId = "find-plain-only-001"
    const collector = new EvidenceCollector(tempDir) // no encryptionEngagementId

    const req = await collector.saveRequest(engId, findingId, "plain content")
    const filePath = join(tempDir, engId, "artifacts", findingId, req.path)
    expect(existsSync(filePath)).toBe(true)
    expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(false)
    expect(readFileSync(filePath, "utf-8")).toBe("plain content")
  })
})
