/**
 * Encryption Test Utilities — shared helpers for encryption integration tests.
 *
 * Reduces boilerplate by providing:
 *   - EncryptionManager lifecycle management (cross-platform: macOS Keychain + file-based)
 *   - Temp directory and store path generation
 *   - EngagementStore encryption flag toggling
 *   - Platform-specific test execution (macOS-only tests)
 *   - Hashing and evidence collector creation
 */
import { test, expect } from "bun:test"
import { mkdtempSync, rmSync } from "node:fs"
import { join } from "node:path"
import { tmpdir, platform } from "node:os"
import crypto from "node:crypto"
import { EngagementStore } from "../../../src/argus/engagement/store"
import { EncryptionManager } from "../../../src/argus/storage/encryption"
import { EvidenceCollector } from "../../../src/argus/evidence/collector"
import { EncryptedFileHandle } from "../../../src/argus/storage/encrypted-file"

// ═══════════════════════════════════════════════════════════════
// Platform helpers
// ═══════════════════════════════════════════════════════════════

/** Whether the current platform is macOS. */
export const IS_MACOS = platform() === "darwin"

/**
 * Run a test only on macOS. On other platforms, the test is skipped.
 * Usage: `itOnMac("test name", async () => { ... }, timeoutMs?)`
 */
export const itOnMac = IS_MACOS ? test : test.skip

// ═══════════════════════════════════════════════════════════════
// Temp directory management
// ═══════════════════════════════════════════════════════════════

/** Create a temporary directory with the given prefix. */
export function makeTempDir(prefix = "argus-test-"): string {
  return mkdtempSync(join(tmpdir(), prefix))
}

/** Remove a temporary directory (recursive, best-effort). */
export function cleanupTempDir(dir: string): void {
  if (dir) {
    try { rmSync(dir, { recursive: true, force: true }) } catch { /* best-effort */ }
  }
}

/**
 * Generate a unique store database path within a temp directory.
 * The temp dir is created on first call (lazy initialization).
 */
export function makeStorePath(tempDir?: string): string {
  const dir = tempDir ?? mkdtempSync(join(tmpdir(), "argus-store-"))
  return join(dir, `test-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`)
}

// ═══════════════════════════════════════════════════════════════
// EncryptionManager lifecycle
// ═══════════════════════════════════════════════════════════════

const DEFAULT_PASSPHRASE = "encryption-test-passphrase-2024"

/**
 * Initialize the EncryptionManager with a fresh key.
 *
 * Works on all platforms:
 *   - macOS: stores key in the OS Keychain via Bun FFI
 *   - Linux/Windows: uses file-based fallback (scrypt + AES-GCM)
 *
 * Sets ARGUS_KEY_PASSPHRASE for Linux file-based fallback if not already set.
 * Destroys any existing key first to ensure a clean state.
 *
 * @returns The master key Buffer (32 bytes)
 */
export async function initEncryptionManager(passphrase?: string): Promise<Buffer> {
  if (!process.env.ARGUS_KEY_PASSPHRASE) {
    process.env.ARGUS_KEY_PASSPHRASE = passphrase ?? DEFAULT_PASSPHRASE
  }
  try { await EncryptionManager.destroy() } catch { /* already clean */ }
  await EncryptionManager.initialize()
  return await EncryptionManager.requireMasterKey()
}

/**
 * Destroy the EncryptionManager key and clear the in-memory cache.
 * Best-effort — does not throw on failure.
 */
export async function destroyEncryptionManager(): Promise<void> {
  try { await EncryptionManager.destroy() } catch { /* best-effort */ }
  EncryptionManager.clearCache()
}

/**
 * Reload the master key into cache (e.g., after clearCache was called by
 * a previous test's teardown).
 */
export async function reloadMasterKey(): Promise<void> {
  await EncryptionManager.requireMasterKey()
}

// ═══════════════════════════════════════════════════════════════
// EngagementStore encryption flag toggling
// ═══════════════════════════════════════════════════════════════

/**
 * Enable encryption on the EngagementStore.
 *
 * IMPORTANT: This must be called AFTER the EngagementStore constructor,
 * because the constructor calls `syncEncryptionFromConfig()` which may
 * override the flag based on config files on disk.
 */
export function withEncryption(): void {
  EngagementStore.encryptionEnabled = true
}

/**
 * Disable encryption on the EngagementStore.
 * Call BEFORE the EngagementStore constructor, or after construction
 * if you want to override the config-based default.
 */
export function withoutEncryption(): void {
  EngagementStore.encryptionEnabled = false
}

// ═══════════════════════════════════════════════════════════════
// EvidenceCollector factory
// ═══════════════════════════════════════════════════════════════

/**
 * Create an EvidenceCollector with encryption enabled for the given engagement.
 * The EncryptionManager must have been initialized and the master key cached
 * before calling this (see `initEncryptionManager`).
 *
 * @param baseDir  Base directory for evidence storage (use tempDir)
 * @param engagementId  Engagement ID for key derivation
 * @returns A configured EvidenceCollector
 */
export function createEncryptedCollector(baseDir: string, engagementId: string): EvidenceCollector {
  return new EvidenceCollector(baseDir, undefined, engagementId)
}

/**
 * Assert that a file on disk is encrypted (detected by EncryptedFileHandle.isEncryptedFile).
 */
export function expectEncrypted(filePath: string): void {
  expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(true)
}

/**
 * Assert that a file on disk is NOT encrypted (plaintext).
 */
export function expectNotEncrypted(filePath: string): void {
  expect(EncryptedFileHandle.isEncryptedFile(filePath)).toBe(false)
}

// ═══════════════════════════════════════════════════════════════
// Hash helper
// ═══════════════════════════════════════════════════════════════

/** Compute the SHA-256 hex digest of a string or Buffer. */
export function sha256(content: string | Buffer): string {
  return crypto.createHash("sha256").update(content).digest("hex")
}

// ═══════════════════════════════════════════════════════════════
// Verify helper
// ═══════════════════════════════════════════════════════════════

/**
 * Verify an encrypted evidence package using the provided master key.
 * Expects it to be valid (passes integrity check).
 */
export async function verifyEncryptedPackage(
  baseDir: string,
  engagementId: string,
  packageId: string,
  masterKey: Buffer,
): Promise<void> {
  const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
  const result = await verifyPackage(baseDir, engagementId, packageId, { masterKey })
  expect(result.valid).toBe(true)
  expect(result.errors).toHaveLength(0)
}

/**
 * Verify that an encrypted evidence package FAILS integrity check
 * when no master key is provided (hash mismatch on encrypted bytes).
 */
export async function expectPackageFailsWithoutKey(
  baseDir: string,
  engagementId: string,
  packageId: string,
): Promise<void> {
  const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
  const result = await verifyPackage(baseDir, engagementId, packageId)
  expect(result.valid).toBe(false)
  expect(result.errors.some((e: string) => e.includes("Hash mismatch"))).toBe(true)
}

/**
 * Verify that an encrypted evidence package FAILS integrity check
 * when a wrong master key is provided (decryption failure).
 */
export async function expectPackageFailsWithWrongKey(
  baseDir: string,
  engagementId: string,
  packageId: string,
): Promise<void> {
  const wrongKey = crypto.randomBytes(32)
  const { verifyPackage } = await import("../../../src/argus/evidence/integrity")
  const result = await verifyPackage(baseDir, engagementId, packageId, { masterKey: wrongKey })
  expect(result.valid).toBe(false)
  expect(result.errors.some((e: string) => e.includes("Failed to decrypt"))).toBe(true)
}
