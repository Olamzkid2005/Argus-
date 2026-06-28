/**
 * EncryptionManager — unit tests
 *
 * Tests the full happy path on macOS: initialize, key storage/retrieval via
 * Keychain (Bun FFI), HKDF key derivation, AES-256-GCM encrypt/decrypt
 * roundtrip, key export/import, and cache behavior.
 *
 * These tests interact with the real macOS Keychain (Security.framework via Bun FFI).
 * On first run, the OS may prompt for keychain access — approve it.
 * Tests are skipped on non-macOS platforms.
 */
import { beforeAll, afterAll, describe, expect, test } from "bun:test"
import { platform } from "node:os"
import { mkdtempSync, readFileSync, rmSync, existsSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"
import crypto from "node:crypto"

// Import the full module — pure methods (deriveEngagementKey, etc.) work on any platform.
// Keychain-dependent methods throw UnsupportedPlatformError on non-macOS.
const { EncryptionManager, EncryptionError } = await import(
  "../../../src/argus/storage/encryption"
)

const isMacOS = platform() === "darwin"

// ── Helpers ──

function makeTempDir(): string {
  return mkdtempSync(join(tmpdir(), "argus-encryption-test-"))
}

function cleanupTempDir(dir: string): void {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* best-effort */ }
}

// ── Tests requiring macOS Keychain ──

// On non-macOS, skip all keychain-dependent tests with a single describe.skip
const macDescriptor = isMacOS ? describe : describe.skip

macDescriptor("EncryptionManager — keychain operations (macOS only)", () => {
  let tempDir: string

  beforeAll(async () => {
    tempDir = makeTempDir()
    // Ensure clean state — delete any leftover test key
    try { await EncryptionManager.destroy() } catch { /* already clean */ }
  })

  afterAll(async () => {
    // Clean up test key from keychain
    try { await EncryptionManager.destroy() } catch { /* best-effort */ }
    cleanupTempDir(tempDir)
  })

  // ── Key lifecycle ──

  test("isInitialized returns false before initialization", async () => {
    // Note: if a key from a previous test run exists, this could fail.
    // We destroy() in beforeAll and afterAll to keep isolated.
    const initialized = await EncryptionManager.isInitialized()
    expect(initialized).toBe(false)
  })

  test("initialize generates and stores a master key", async () => {
    const created = await EncryptionManager.initialize()
    expect(created).toBe(true)

    const initialized = await EncryptionManager.isInitialized()
    expect(initialized).toBe(true)
  })

  test("initialize is idempotent (returns false on re-run)", async () => {
    const created = await EncryptionManager.initialize()
    expect(created).toBe(false) // already exists from previous test
  })

  test("getMasterKey retrieves the stored key", async () => {
    const key = await EncryptionManager.getMasterKey()
    expect(key).not.toBeNull()
    expect(key!.length).toBe(32) // 256 bits
  })

  test("requireMasterKey returns key when initialized", async () => {
    const key = await EncryptionManager.requireMasterKey()
    expect(key).not.toBeNull()
    expect(key.length).toBe(32)
  })

  test("getMasterKey returns consistent key on multiple calls", async () => {
    const key1 = await EncryptionManager.getMasterKey()
    const key2 = await EncryptionManager.getMasterKey()
    expect(key1).toEqual(key2)
  })

  test("clearCache forces fresh keychain read on next getMasterKey", async () => {
    EncryptionManager.clearCache()
    const key = await EncryptionManager.getMasterKey()
    expect(key).not.toBeNull()
    expect(key!.length).toBe(32)
  })

  // ── HKDF key derivation ──

  test("deriveEngagementKey produces a deterministic 32-byte key", () => {
    const masterKey = crypto.randomBytes(32)
    const derived = EncryptionManager.deriveEngagementKey(masterKey, "ENG-test-123")
    expect(derived).toBeInstanceOf(Buffer)
    expect(derived.length).toBe(32)
  })

  test("deriveEngagementKey produces unique keys for different engagement IDs", () => {
    const masterKey = crypto.randomBytes(32)
    const derived1 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-aaa")
    const derived2 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-bbb")
    expect(derived1).not.toEqual(derived2)
  })

  test("deriveEngagementKey produces different keys from different master keys", () => {
    const mk1 = crypto.randomBytes(32)
    const mk2 = crypto.randomBytes(32)
    const d1 = EncryptionManager.deriveEngagementKey(mk1, "ENG-test")
    const d2 = EncryptionManager.deriveEngagementKey(mk2, "ENG-test")
    expect(d1).not.toEqual(d2)
  })

  test("deriveFileKey produces a deterministic 32-byte key", () => {
    const masterKey = crypto.randomBytes(32)
    const derived = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "file-1")
    expect(derived).toBeInstanceOf(Buffer)
    expect(derived.length).toBe(32)
  })

  test("deriveFileKey produces different keys for different file IDs", () => {
    const masterKey = crypto.randomBytes(32)
    const d1 = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "file-a")
    const d2 = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "file-b")
    expect(d1).not.toEqual(d2)
  })

  test("deriveFileKey and deriveEngagementKey produce different keys (domain separation)", () => {
    const masterKey = crypto.randomBytes(32)
    const engKey = EncryptionManager.deriveEngagementKey(masterKey, "ENG-test")
    const fileKey = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "ENG-test")
    expect(engKey).not.toEqual(fileKey)
  })

  // ── AES-256-GCM encrypt/decrypt ──

  test("encryptEngagementDb / decryptEngagementDb roundtrip", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("Hello, encrypted engagement DB!", "utf-8")

    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-roundtrip-1")
    expect(encrypted).not.toEqual(plaintext) // actually encrypted

    const decrypted = EncryptionManager.decryptEngagementDb(encrypted, masterKey, "ENG-roundtrip-1")
    expect(decrypted.toString("utf-8")).toBe("Hello, encrypted engagement DB!")
  })

  test("encryptEngagementDb produces different ciphertext for same plaintext (different salt+IV)", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("same data", "utf-8")

    const enc1 = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-nonce")
    const enc2 = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-nonce")

    expect(enc1).not.toEqual(enc2) // different salt/IV → different ciphertext
    // Both should decrypt to the same plaintext
    expect(EncryptionManager.decryptEngagementDb(enc1, masterKey, "ENG-nonce")).toEqual(plaintext)
    expect(EncryptionManager.decryptEngagementDb(enc2, masterKey, "ENG-nonce")).toEqual(plaintext)
  })

  test("decryptEngagementDb rejects wrong engagement ID (wrong derived key)", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("secret data", "utf-8")

    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-correct-id")

    expect(() => {
      EncryptionManager.decryptEngagementDb(encrypted, masterKey, "ENG-wrong-id")
    }).toThrow() // GCM auth tag mismatch
  })

  test("decryptEngagementDb rejects tampered ciphertext", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("tamper test", "utf-8")

    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-tamper")
    // Corrupt a byte in the ciphertext
    encrypted[encrypted.length - 1] ^= 0xff

    expect(() => {
      EncryptionManager.decryptEngagementDb(encrypted, masterKey, "ENG-tamper")
    }).toThrow() // GCM auth tag verification fails
  })

  test("encryptEngagementDb handles empty buffer", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.alloc(0)

    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-empty")
    const decrypted = EncryptionManager.decryptEngagementDb(encrypted, masterKey, "ENG-empty")
    expect(decrypted.length).toBe(0)
  })

  test("encryptEngagementDb handles large buffer (1 MB)", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = crypto.randomBytes(1024 * 1024) // 1 MB

    const encrypted = EncryptionManager.encryptEngagementDb(plaintext, masterKey, "ENG-large")
    const decrypted = EncryptionManager.decryptEngagementDb(encrypted, masterKey, "ENG-large")
    expect(decrypted).toEqual(plaintext)
  })

  // ── File encrypt/decrypt ──

  test("encryptFile / decryptFile roundtrip", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("evidence file content", "utf-8")

    const encrypted = EncryptionManager.encryptFile(plaintext, masterKey, "ENG-file-test", "screenshot-1")
    expect(encrypted).not.toEqual(plaintext)

    const decrypted = EncryptionManager.decryptFile(encrypted, masterKey, "ENG-file-test", "screenshot-1")
    expect(decrypted.toString("utf-8")).toBe("evidence file content")
  })

  test("encryptFile / decryptFile binary data roundtrip (PNG bytes)", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    // Simulate a small PNG-like binary blob
    const plaintext = crypto.randomBytes(4096)

    const encrypted = EncryptionManager.encryptFile(plaintext, masterKey, "ENG-bin", "screenshot.png")
    const decrypted = EncryptionManager.decryptFile(encrypted, masterKey, "ENG-bin", "screenshot.png")
    expect(decrypted).toEqual(plaintext)
  })

  test("decryptFile rejects wrong file ID", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const plaintext = Buffer.from("file content", "utf-8")

    const encrypted = EncryptionManager.encryptFile(plaintext, masterKey, "ENG-f", "correct-file-id")

    expect(() => {
      EncryptionManager.decryptFile(encrypted, masterKey, "ENG-f", "wrong-file-id")
    }).toThrow()
  })

  // ── Key export/import ──

  test("exportKey creates an encrypted backup file", async () => {
    await EncryptionManager.initialize()
    const backupPath = join(tempDir, "test-master-key.enc")

    await EncryptionManager.exportKey("test-passphrase-123!", backupPath)

    expect(existsSync(backupPath)).toBe(true)
    const data = readFileSync(backupPath)
    // Format: salt (16) + iv (12) + ciphertext (32) + authTag (16) = 76 bytes
    expect(data.length).toBe(16 + 12 + 32 + 16)
  })

  test("importKey restores a previously exported key", async () => {
    // First, create a fresh key, export it, then destroy it
    await EncryptionManager.initialize()
    const backupPath = join(tempDir, "import-test-key.enc")
    await EncryptionManager.exportKey("backup-passphrase", backupPath)

    // Get the current master key value to compare after import
    const originalKey = await EncryptionManager.requireMasterKey()

    // Destroy and re-create to get a different key
    await EncryptionManager.destroy()
    await EncryptionManager.initialize()
    const differentKey = await EncryptionManager.requireMasterKey()
    expect(differentKey).not.toEqual(originalKey) // random, should differ

    // Now destroy again and import
    await EncryptionManager.destroy()

    // Verify not initialized
    expect(await EncryptionManager.isInitialized()).toBe(false)

    // Import the backup
    await EncryptionManager.importKey("backup-passphrase", backupPath)

    // Verify the restored key matches the original
    const restoredKey = await EncryptionManager.requireMasterKey()
    expect(restoredKey).toEqual(originalKey)
    expect(await EncryptionManager.isInitialized()).toBe(true)
  })

  test("importKey rejects wrong passphrase", async () => {
    const backupPath = join(tempDir, "wrong-passphrase-test.enc")
    await EncryptionManager.exportKey("correct-passphrase", backupPath)

    expect(async () => {
      await EncryptionManager.importKey("wrong-passphrase", backupPath)
    }).toThrow()
  })

  test("exportKey uses default filename when not specified", async () => {
    const cwd = process.cwd()
    const defaultPath = join(cwd, "argus-master-key.enc")
    try {
      await EncryptionManager.exportKey("default-path-test")
      expect(existsSync(defaultPath)).toBe(true)
    } finally {
      try { rmSync(defaultPath, { force: true }) } catch { /* best-effort cleanup */ }
    }
  })

  // ── Error handling ──

  test("decryptEngagementDb throws on corrupt data (too short)", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    const corrupt = Buffer.alloc(5)
    expect(() => {
      EncryptionManager.decryptEngagementDb(corrupt, masterKey, "ENG-corrupt")
    }).toThrow("too short or corrupted")
  })

  test("decryptEngagementDb throws on unknown version byte", async () => {
    const masterKey = await EncryptionManager.requireMasterKey()
    // Version 0x00 is unknown (bit 0 not set, fails the version check)
    const badVersion = Buffer.alloc(1 + 16 + 12 + 16 + 16)
    badVersion[0] = 0x00
    expect(() => {
      EncryptionManager.decryptEngagementDb(badVersion, masterKey, "ENG-bad-ver")
    }).toThrow("Unsupported encryption format version")
  })

  test("encryptEngagementDb and decryptEngagementDb are usable on the real master key", async () => {
    // Full integration: use the actual keychain-stored master key
    const masterKey = await EncryptionManager.requireMasterKey()
    const original = Buffer.from("Real engagement data with credentials and findings", "utf-8")
    const ciphertext = EncryptionManager.encryptEngagementDb(original, masterKey, "ENG-integration-test")
    const recovered = EncryptionManager.decryptEngagementDb(ciphertext, masterKey, "ENG-integration-test")
    expect(recovered.toString()).toBe("Real engagement data with credentials and findings")
  })

  test("requireMasterKey throws KeyNotFoundError when not initialized", async () => {
    // This test must be LAST in this describe block because it destroys the key
    // All subsequent keychain-requiring tests must come before this one.
    await EncryptionManager.destroy()
    await expect(EncryptionManager.requireMasterKey()).rejects.toThrow("Master key not found")
  })
})

// ── Platform-agnostic tests (no keychain required ── run everywhere) ──

describe("EncryptionManager — pure derivation methods", () => {
  test("deriveEngagementKey is deterministic (same inputs → same output)", () => {
    const masterKey = Buffer.alloc(32, 0xAB)
    const d1 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-deterministic")
    const d2 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-deterministic")
    expect(d1).toEqual(d2)
  })

  test("deriveFileKey is deterministic", () => {
    const masterKey = Buffer.alloc(32, 0xCD)
    const d1 = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "file-1")
    const d2 = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "file-1")
    expect(d1).toEqual(d2)
  })

  test("deriveEngagementKey produces different keys for different engagement IDs", () => {
    const masterKey = Buffer.alloc(32, 0xEF)
    const d1 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-aaa")
    const d2 = EncryptionManager.deriveEngagementKey(masterKey, "ENG-bbb")
    expect(d1).not.toEqual(d2)
  })

  test("deriveFileKey and deriveEngagementKey produce different keys (domain separation)", () => {
    const masterKey = Buffer.alloc(32, 0x01)
    const engKey = EncryptionManager.deriveEngagementKey(masterKey, "ENG-test")
    const fileKey = EncryptionManager.deriveFileKey(masterKey, "ENG-test", "ENG-test")
    expect(engKey).not.toEqual(fileKey)
  })

  test("all derived keys are 32 bytes", () => {
    const masterKey = Buffer.alloc(32, 0xBB)
    expect(EncryptionManager.deriveEngagementKey(masterKey, "ENG-len").length).toBe(32)
    expect(EncryptionManager.deriveFileKey(masterKey, "ENG-len", "f").length).toBe(32)
  })
})
