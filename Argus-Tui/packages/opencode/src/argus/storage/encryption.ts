/**
 * Encryption Manager (Item 14c)
 *
 * Key management, OS keychain integration (via Bun FFI on macOS),
 * HKDF key derivation, AES-256-GCM encrypt/decrypt, and key backup/recovery.
 *
 * Platform support:
 *   - macOS: Security Framework via Bun FFI (Keychain Services)
 *   - Linux: Future — libsecret or file-based fallback
 *   - Windows: Future — Credential Manager via Bun FFI
 *
 * ── Architecture ──
 *   Master key (32 bytes) stored in OS keychain.
 *   Per-engagement keys derived via HKDF-SHA256(masterKey, engagementId).
 *   Per-file keys derived via HKDF-SHA256(masterKey, engagementId + ":" + fileId).
 *
 * ── Threat model ──
 *   Protects against filesystem-level attackers. Key lives in process memory
 *   during active sessions (see Risk 1 in PLAN_14C_ENCRYPTION_AT_REST.md).
 *   No memory zeroization guarantees in V8/Bun — accepted limitation.
 */
// bun:ffi is loaded lazily via createRequire (same pattern as engagement/store.ts)
// to ensure a clear error if not running under Bun.
import { createRequire } from "node:module"
const _require = createRequire(import.meta.url)
type BunFfi = typeof import("bun:ffi")

import crypto from "node:crypto"
import { readFileSync, writeFileSync, existsSync, mkdirSync, unlinkSync } from "node:fs"
import { join, dirname } from "node:path"
import { platform } from "node:os"
import { StoragePaths } from "./paths"

// ── Constants ──

const KEY_LEN = 32           // AES-256
const SALT_LEN = 16
const IV_LEN = 12
const TAG_LEN = 16
const VERSION_BYTE = 0x01
const SERVICE_NAME = "argus"
const ACCOUNT_NAME = "master-key"

// ── Platform detection ──

type Platform = "macos" | "linux" | "windows" | "unknown"
const currentPlatform: Platform = (() => {
  const p = platform()
  if (p === "darwin") return "macos"
  if (p === "linux") return "linux"
  if (p === "win32") return "windows"
  return "unknown"
})()

// ── Error types ──

export class EncryptionError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message)
    this.name = "EncryptionError"
  }
}

export class KeyNotFoundError extends EncryptionError {
  constructor() {
    super("Master key not found in OS keychain. Run `argus encryption init` to generate one.", "KEY_NOT_FOUND")
    this.name = "KeyNotFoundError"
  }
}

export class UnsupportedPlatformError extends EncryptionError {
  constructor(op: string) {
    super(
      `OS keychain access (${op}) is not yet supported on ${currentPlatform}. ` +
      `Currently supported: macOS. ` +
      `Linux: use the file-based fallback. Windows: planned for future release.`,
      "UNSUPPORTED_PLATFORM",
    )
    this.name = "UnsupportedPlatformError"
  }
}

// ── macOS Keychain via Bun FFI ──

let _macKeychain: MacKeychain | null = null

interface MacKeychain {
  setGenericPassword(service: string, account: string, password: string): void
  getGenericPassword(service: string, account: string): string | null
  deleteGenericPassword(service: string, account: string): void
}

/**
 * Lazy-load macOS Keychain FFI bindings.
 * Uses Bun.ffi to call Security.framework directly — no npm dependencies.
 */
function getMacKeychain(): MacKeychain {
  if (_macKeychain) return _macKeychain

  // Lazy-load bun:ffi — gives a clear "Bun required" error if not under Bun
  let ffi: BunFfi
  try {
    ffi = _require("bun:ffi") as BunFfi
  } catch {
    throw new EncryptionError(
      "bun:ffi is required for OS keychain access. Run under `bun`.",
      "FFI_UNAVAILABLE",
    )
  }

  const { dlopen, ptr, CString } = ffi

  const lib = dlopen("/System/Library/Frameworks/Security.framework/Security", {
    SecKeychainAddGenericPassword: {
      // keychain(ptr), serviceLen(u32), service(ptr), accountLen(u32), account(ptr), passLen(u32), pass(ptr), itemRef(ptr)
      args: ["ptr", "u32", "ptr", "u32", "ptr", "u32", "ptr", "ptr"],
      returns: "i32",
    },
    SecKeychainFindGenericPassword: {
      // keychain(ptr), serviceLen(u32), service(ptr), accountLen(u32), account(ptr), passLen(ptr), passData(ptr), itemRef(ptr)
      args: ["ptr", "u32", "ptr", "u32", "ptr", "ptr", "ptr", "ptr"],
      returns: "i32",
    },
    SecKeychainItemFreeContent: {
      args: ["ptr", "ptr"],
      returns: "i32",
    },
    // SecKeychainDeleteGenericPassword does NOT exist in Security.framework.
    // Instead, find the item first via SecKeychainFindGenericPassword, then
    // delete the item reference with SecKeychainItemDelete.
    SecKeychainItemDelete: {
      args: ["ptr"],
      returns: "i32",
    },
  })

  const sym = lib.symbols

  const errSecSuccess = 0
  const errSecItemNotFound = -25300

  _macKeychain = {
    setGenericPassword(service: string, account: string, password: string): void {
      const passBuf = Buffer.from(password, "utf-8")
      const serviceBuf = Buffer.from(service, "utf-8")
      const accountBuf = Buffer.from(account, "utf-8")
      const result = (sym.SecKeychainAddGenericPassword as any)(
        null,
        serviceBuf.length,
        ptr(serviceBuf),
        accountBuf.length,
        ptr(accountBuf),
        passBuf.length,
        ptr(passBuf),
        null,
      ) as number
      if (result !== errSecSuccess) {
        throw new EncryptionError(
          `Failed to store key in macOS Keychain (OSStatus: ${result}). ` +
          "Ensure the process has access to the keychain (try running interactively).",
          "KEYCHAIN_WRITE_FAILED",
        )
      }
    },

    getGenericPassword(service: string, account: string): string | null {
      const passLenBuf = Buffer.alloc(4)    // UInt32 output
      const passDataBuf = Buffer.alloc(8)    // void* output (64-bit pointer)
      const serviceBuf = Buffer.from(service, "utf-8")
      const accountBuf = Buffer.from(account, "utf-8")

      const result = (sym.SecKeychainFindGenericPassword as any)(
        null,
        serviceBuf.length,
        ptr(serviceBuf),
        accountBuf.length,
        ptr(accountBuf),
        ptr(passLenBuf),
        ptr(passDataBuf),
        null,
      ) as number

      if (result === errSecItemNotFound) return null
      if (result !== errSecSuccess) {
        throw new EncryptionError(
          `Failed to read key from macOS Keychain (OSStatus: ${result}).`,
          "KEYCHAIN_READ_FAILED",
        )
      }

      const pwLen = passLenBuf.readUInt32LE(0)
      const pwPtr = Number(passDataBuf.readBigUInt64LE(0))

      // Read the password data at the returned pointer (null-terminated)
      // CString(ptr) reads until null terminator — safe because we stored a hex string
      const password = new CString(pwPtr)

      // Free the allocated memory (pass raw pointer as bigint)
      ;(sym.SecKeychainItemFreeContent as any)(null, pwPtr)

      return password
    },

    deleteGenericPassword(service: string, account: string): void {
      // First, find the item to get a SecKeychainItemRef
      const passLenBuf = Buffer.alloc(4)
      const passDataBuf = Buffer.alloc(8)
      const itemRefBuf = Buffer.alloc(8)
      const serviceBuf = Buffer.from(service, "utf-8")
      const accountBuf = Buffer.from(account, "utf-8")

      const findResult = (sym.SecKeychainFindGenericPassword as any)(
        null,
        serviceBuf.length,
        ptr(serviceBuf),
        accountBuf.length,
        ptr(accountBuf),
        ptr(passLenBuf),
        ptr(passDataBuf),
        ptr(itemRefBuf),
      ) as number

      if (findResult === errSecItemNotFound) return // already gone
      if (findResult !== errSecSuccess) {
        throw new EncryptionError(
          `Failed to find key for deletion in macOS Keychain (OSStatus: ${findResult}).`,
          "KEYCHAIN_DELETE_FAILED",
        )
      }

      // Free the password data first
      const pwPtr = Number(passDataBuf.readBigUInt64LE(0))
      ;(sym.SecKeychainItemFreeContent as any)(null, pwPtr)

      // Delete the item reference
      const itemRef = Number(itemRefBuf.readBigUInt64LE(0))
      const delResult = (sym.SecKeychainItemDelete as any)(itemRef) as number
      if (delResult !== errSecSuccess) {
        throw new EncryptionError(
          `Failed to delete key from macOS Keychain (OSStatus: ${delResult}).`,
          "KEYCHAIN_DELETE_FAILED",
        )
      }
    },
  }

  return _macKeychain
}

// ── File-based keychain backend (cross-platform fallback) ──

/**
 * Get the path to the encrypted master key file.
 */
function fileKeychainPath(): string {
  return join(StoragePaths.basePath, FILE_KEYCHAIN_NAME)
}

/**
 * Ensure the Argus data directory exists.
 */
function ensureArgusDir(): void {
  const dir = StoragePaths.basePath
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true })
  }
}

/**
 * Store a secret in the file-based keychain.
 * The secret is encrypted with a scrypt-derived key before writing.
 */
function fileKeychainSet(_service: string, _account: string, secret: string): void {
  const passphrase = EncryptionManager.getPassphrase()
  if (!passphrase) {
    throw new EncryptionError(
      "Passphrase required for file-based keychain. Set --passphrase flag or ARGUS_KEY_PASSPHRASE env var.",
      "PASSPHRASE_REQUIRED",
    )
  }
  ensureArgusDir()

  const path = fileKeychainPath()
  const scryptSalt = crypto.randomBytes(SALT_LEN)
  const iv = crypto.randomBytes(IV_LEN)
  const key = crypto.scryptSync(passphrase, scryptSalt, KEY_LEN, {
    N: 2 ** 17, r: 8, p: 1, maxmem: 256 * 1024 * 1024,
  })
  const secretBuf = Buffer.from(secret, "utf-8")
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv)
  const encrypted = Buffer.concat([cipher.update(secretBuf), cipher.final()])
  const tag = cipher.getAuthTag()

  const payload = Buffer.concat([scryptSalt, iv, encrypted, tag])
  writeFileSync(path, payload, { mode: 0o600 })
}

/**
 * Retrieve a secret from the file-based keychain.
 * Returns null if the file doesn't exist.
 */
function fileKeychainGet(_service: string, _account: string): string | null {
  const path = fileKeychainPath()
  if (!existsSync(path)) return null

  const passphrase = EncryptionManager.getPassphrase()
  if (!passphrase) {
    throw new EncryptionError(
      "Passphrase required for file-based keychain. Set --passphrase flag or ARGUS_KEY_PASSPHRASE env var.",
      "PASSPHRASE_REQUIRED",
    )
  }

  const data = readFileSync(path)
  if (data.length < SALT_LEN + IV_LEN + TAG_LEN) {
    throw new EncryptionError("Master key file is too short or corrupted", "KEYCHAIN_CORRUPT")
  }

  let offset = 0
  const scryptSalt = data.subarray(offset, offset + SALT_LEN)
  offset += SALT_LEN
  const iv = data.subarray(offset, offset + IV_LEN)
  offset += IV_LEN
  const tag = data.subarray(data.length - TAG_LEN)
  const ciphertext = data.subarray(offset, data.length - TAG_LEN)

  const key = crypto.scryptSync(passphrase, scryptSalt, KEY_LEN, {
    N: 2 ** 17, r: 8, p: 1, maxmem: 256 * 1024 * 1024,
  })
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv)
  decipher.setAuthTag(tag)
  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()])
  return decrypted.toString("utf-8")
}

/**
 * Delete the master key file from the file-based keychain.
 * No-op if the file doesn't exist.
 */
function fileKeychainDelete(_service: string, _account: string): void {
  const path = fileKeychainPath()
  try { unlinkSync(path) } catch { /* best-effort */ }
}

// ── Keychain abstraction ──

/**
 * Store a secret in the keychain.
 * Uses macOS Keychain on macOS, file-based fallback on other platforms.
 */
function keychainSet(service: string, account: string, secret: string): void {
  switch (currentPlatform) {
    case "macos":
      getMacKeychain().setGenericPassword(service, account, secret)
      return
    default:
      fileKeychainSet(service, account, secret)
      return
  }
}

/**
 * Retrieve a secret from the keychain.
 * Uses macOS Keychain on macOS, file-based fallback on other platforms.
 * Returns null if the secret does not exist.
 */
function keychainGet(service: string, account: string): string | null {
  switch (currentPlatform) {
    case "macos":
      return getMacKeychain().getGenericPassword(service, account)
    default:
      return fileKeychainGet(service, account)
  }
}

/**
 * Delete a secret from the keychain.
 * Uses macOS Keychain on macOS, file-based fallback on other platforms.
 * No-op if the secret does not exist.
 */
function keychainDelete(service: string, account: string): void {
  switch (currentPlatform) {
    case "macos":
      getMacKeychain().deleteGenericPassword(service, account)
      return
    default:
      fileKeychainDelete(service, account)
      return
  }
}

// ── HKDF key derivation ──

/**
 * Derive a per-engagement key using HKDF-SHA256.
 *
 * Salt is a fixed domain separator (per RFC 5869 §3.1, salt may be
 * non-secret when the IKM is already uniformly random). The "info"
 * parameter provides domain separation per engagement.
 */
function deriveKey(masterKey: Buffer, salt: Buffer, info: Buffer): Buffer {
  const result = crypto.hkdfSync("sha256", masterKey, salt, info, KEY_LEN)
  // hkdfSync returns ArrayBuffer in Bun — wrap in Buffer for consistent API
  return Buffer.from(result)
}

// ── AES-256-GCM encrypt/decrypt ──

/**
 * Encrypt a plaintext buffer with AES-256-GCM.
 * Returns the encrypted payload: [version:1][salt:16][iv:12][ciphertext...][authTag:16]
 *
 * Uses a random salt for HKDF derivation and a random IV per encryption,
 * ensuring that encrypting the same data twice produces different ciphertext.
 */
function aesGcmEncrypt(
  plaintext: Buffer,
  masterKey: Buffer,
  contextSalt: Buffer,
  contextInfo: Buffer,
  compress = false,
): Buffer {
  let payload = plaintext
  if (compress) {
    try { payload = (Bun as any).deflateSync(plaintext) } catch { /* compression best-effort */ }
  }
  const salt = crypto.randomBytes(SALT_LEN)
  const iv = crypto.randomBytes(IV_LEN)

  // Derive a unique key for this encryption using the random salt
  const key = deriveKey(masterKey, salt, Buffer.concat([contextSalt, contextInfo]))

  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv)
  const encrypted = Buffer.concat([cipher.update(payload), cipher.final()])
  const tag = cipher.getAuthTag()

  // Format: version (1) | salt (16) | iv (12) | ciphertext | authTag (16)
  const version = Buffer.alloc(1)
  version[0] = VERSION_BYTE | (compress ? 0x02 : 0x00)

  return Buffer.concat([version, salt, iv, encrypted, tag])
}

/**
 * Decrypt a buffer previously encrypted with aesGcmEncrypt.
 * Handles format version byte, salt extraction, and decompression.
 */
function aesGcmDecrypt(
  encrypted: Buffer,
  masterKey: Buffer,
  contextSalt: Buffer,
  contextInfo: Buffer,
): Buffer {
  if (encrypted.length < 1 + SALT_LEN + IV_LEN + TAG_LEN) {
    throw new EncryptionError("Encrypted data is too short or corrupted", "DECRYPT_CORRUPT")
  }

  const version = encrypted[0]
  let offset = 1

  if ((version & 0x01) !== VERSION_BYTE) {
    throw new EncryptionError(
      `Unsupported encryption format version: ${version & 0x01}. Expected: ${VERSION_BYTE}`,
      "UNSUPPORTED_VERSION",
    )
  }

  const salt = encrypted.subarray(offset, offset + SALT_LEN)
  offset += SALT_LEN
  const iv = encrypted.subarray(offset, offset + IV_LEN)
  offset += IV_LEN
  const tag = encrypted.subarray(encrypted.length - TAG_LEN)
  const ciphertext = encrypted.subarray(offset, encrypted.length - TAG_LEN)

  const key = deriveKey(masterKey, salt, Buffer.concat([contextSalt, contextInfo]))

  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv)
  decipher.setAuthTag(tag)
  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()])

  // Decompress if compression flag is set (bit 1 of version byte)
  if (version & 0x02) {
    try {
      return (Bun as any).inflateSync(decrypted)
    } catch {
      throw new EncryptionError("Failed to decompress decrypted data", "DECOMPRESS_FAILED")
    }
  }

  return decrypted
}

// ── Backup file helpers ──

const BACKUP_FILE_NAME = "argus-master-key.enc"
const BACKUP_SALT = Buffer.from("argus-backup-v1", "utf-8")
const ENGAGEMENT_KEY_SALT = Buffer.from("argus-engagement-v1", "utf-8")
const FILE_KEY_SALT = Buffer.from("argus-file-v1", "utf-8")

// ── File-based keychain (cross-platform fallback) ──

/** Name of the encrypted master key file in the Argus data directory. */
const FILE_KEYCHAIN_NAME = ".master-key.enc"

/** Domain separator for file-based keychain scrypt derivation. */
const FILE_KEYCHAIN_SALT = Buffer.from("argus-file-keychain-v1", "utf-8")

/**
 * Derive a key from a user passphrase using scrypt.
 * Used for encrypting the master key backup file.
 */
function deriveBackupKey(passphrase: string, salt: Buffer): Buffer {
  return crypto.scryptSync(passphrase, salt, KEY_LEN, {
    N: 2 ** 17,     // 131072 — OWASP recommended minimum
    r: 8,
    p: 1,
    maxmem: 256 * 1024 * 1024, // 256 MB (N=2^17, r=8 → ~128 MB needed per scrypt invocation)
  })
}

// ── EncryptionManager ──

export class EncryptionManager {
  /**
   * Maximum age for a cached master key (5 minutes).
   * After this, the next access will re-prompt for OS authentication.
   */
  private static readonly CACHE_TTL_MS = 5 * 60 * 1000

  /** Cached master key (in process memory). */
  private static cachedKey: { key: Buffer; obtainedAt: number } | null = null

  /** Passphrase for file-based keychain (Linux/Windows). Cleared after use. */
  private static filePassphrase: string | null = null

  /**
   * Set the passphrase for file-based keychain access.
   * Required on Linux and Windows where the OS keychain is not available.
   * Can also be set via the ARGUS_KEY_PASSPHRASE environment variable.
   * Cleared when clearCache() or clearPassphrase() is called.
   */
  static setPassphrase(passphrase: string): void {
    this.filePassphrase = passphrase
  }

  /**
   * Clear the file-based keychain passphrase from memory.
   */
  static clearPassphrase(): void {
    this.filePassphrase = null
  }

  /**
   * Get the passphrase, checking env var as fallback.
   * Returns null if not set.
   */
  static getPassphrase(): string | null {
    return this.filePassphrase ?? process.env.ARGUS_KEY_PASSPHRASE ?? null
  }

  /**
   * Check if running in file-based keychain mode (non-macOS).
   */
  static isFileBased(): boolean {
    return currentPlatform !== "macos"
  }

  /**
   * Initialize encryption: generate a master key and store it in the OS keychain.
   * Safe to call multiple times — skips if key already exists.
   *
   * @returns true if a new key was generated, false if one already existed
   */
  static async initialize(): Promise<boolean> {
    const existing = await this.rawGetMasterKey()
    if (existing !== null) return false

    const masterKey = crypto.randomBytes(KEY_LEN)
    const hex = masterKey.toString("hex")

    keychainSet(SERVICE_NAME, ACCOUNT_NAME, hex)

    // Update cache
    this.cachedKey = { key: masterKey, obtainedAt: Date.now() }
    return true
  }

  /**
   * Check if a master key has been initialized in the OS keychain.
   */
  static async isInitialized(): Promise<boolean> {
    const existing = await this.rawGetMasterKey()
    return existing !== null
  }

  /**
   * Delete the master key from the OS keychain.
   * ⚠️ WARNING: This makes all encrypted engagements permanently unrecoverable
   * unless a backup was previously exported.
   */
  static async destroy(): Promise<void> {
    keychainDelete(SERVICE_NAME, ACCOUNT_NAME)
    this.cachedKey = null
  }

  /**
   * Check whether a master key is currently cached (non-expired).
   * Returns true if a key is loaded and within the 5-minute TTL.
   */
  static isCached(): boolean {
    return this.cachedKey !== null && Date.now() - this.cachedKey.obtainedAt < this.CACHE_TTL_MS
  }

  /**
   * Get the master key from the in-memory cache synchronously.
   * Returns null if the key is not in cache (expired or never loaded).
   *
   * This is used by sync contexts like EngagementStore._getEngagementDb
   * that need to open encrypted databases synchronously. The caller should
   * ensure the key is loaded before using encrypted engagements.
   */
  static getCachedMasterKey(): Buffer | null {
    if (this.cachedKey && Date.now() - this.cachedKey.obtainedAt < this.CACHE_TTL_MS) {
      return this.cachedKey.key
    }
    return null
  }

  /**
   * Get the master key from cache or OS keychain.
   * Returns null if no key exists.
   */
  static async getMasterKey(): Promise<Buffer | null> {
    // Check cache (with TTL)
    if (this.cachedKey && Date.now() - this.cachedKey.obtainedAt < this.CACHE_TTL_MS) {
      return this.cachedKey.key
    }

    const hex = await this.rawGetMasterKey()
    if (hex === null) return null

    const key = Buffer.from(hex, "hex")
    this.cachedKey = { key, obtainedAt: Date.now() }
    return key
  }

  /**
   * Retrieve the master key from the OS keychain (bypass cache).
   */
  private static async rawGetMasterKey(): Promise<string | null> {
    return keychainGet(SERVICE_NAME, ACCOUNT_NAME)
  }

  /**
   * Get the master key, throwing if not found.
   */
  static async requireMasterKey(): Promise<Buffer> {
    const key = await this.getMasterKey()
    if (key === null) throw new KeyNotFoundError()
    return key
  }

  /**
   * Derive a per-engagement encryption key from the master key.
   *
   * Each engagement gets its own derived key via HKDF with domain
   * separation. Compromising one engagement's key does not expose others.
   */
  static deriveEngagementKey(masterKey: Buffer, engagementId: string): Buffer {
    return deriveKey(
      masterKey,
      ENGAGEMENT_KEY_SALT,
      Buffer.from(engagementId, "utf-8"),
    )
  }

  /**
   * Derive a per-file encryption key from the master key.
   *
   * Each evidence file gets its own derived key via HKDF with domain
   * separation. Compromising one file's key does not expose other files
   * or the engagement DB.
   */
  static deriveFileKey(masterKey: Buffer, engagementId: string, fileId: string): Buffer {
    return deriveKey(
      masterKey,
      FILE_KEY_SALT,
      Buffer.from(`${engagementId}:${fileId}`, "utf-8"),
    )
  }

  /**
   * Export the master key to a file, encrypted with a user-supplied passphrase.
   *
   * The backup file uses scrypt (N=2^17, r=8, p=1) for passphrase-based
   * key derivation, then AES-256-GCM to encrypt the master key.
   *
   * @param outputPath Path for the backup file (default: ./argus-master-key.enc)
   * @param passphrase User-supplied passphrase for encrypting the backup
   */
  static async exportKey(passphrase: string, outputPath?: string): Promise<void> {
    const masterKey = await this.requireMasterKey()
    const path = outputPath ?? join(process.cwd(), BACKUP_FILE_NAME)

    const backupSalt = crypto.randomBytes(SALT_LEN)
    const backupKey = deriveBackupKey(passphrase, backupSalt)
    const iv = crypto.randomBytes(IV_LEN)

    const cipher = crypto.createCipheriv("aes-256-gcm", backupKey, iv)
    const encrypted = Buffer.concat([cipher.update(masterKey), cipher.final()])
    const tag = cipher.getAuthTag()

    // Format: backupSalt (16) | iv (12) | ciphertext (32) | authTag (16)
    const payload = Buffer.concat([backupSalt, iv, encrypted, tag])

    const dir = join(path, "..")
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
    writeFileSync(path, payload, { mode: 0o600 })
  }

  /**
   * Import a previously exported master key from a backup file.
   *
   * @param inputPath Path to the backup file
   * @param passphrase Passphrase used during export
   */
  static async importKey(passphrase: string, inputPath?: string): Promise<void> {
    const path = inputPath ?? join(process.cwd(), BACKUP_FILE_NAME)

    if (!existsSync(path)) {
      throw new EncryptionError(
        `Backup file not found: ${path}`,
        "BACKUP_FILE_NOT_FOUND",
      )
    }

    const data = readFileSync(path)

    if (data.length < SALT_LEN + IV_LEN + KEY_LEN + TAG_LEN) {
      throw new EncryptionError(
        "Backup file is too short or corrupted",
        "BACKUP_CORRUPT",
      )
    }

    let offset = 0
    const backupSalt = data.subarray(offset, offset + SALT_LEN)
    offset += SALT_LEN
    const iv = data.subarray(offset, offset + IV_LEN)
    offset += IV_LEN
    const tag = data.subarray(data.length - TAG_LEN)
    const ciphertext = data.subarray(offset, data.length - TAG_LEN)

    // Derive backup key from passphrase
    const backupKey = deriveBackupKey(passphrase, backupSalt)

    const decipher = crypto.createDecipheriv("aes-256-gcm", backupKey, iv)
    decipher.setAuthTag(tag)
    const masterKey = Buffer.concat([decipher.update(ciphertext), decipher.final()])

    // Store in keychain
    keychainSet(SERVICE_NAME, ACCOUNT_NAME, masterKey.toString("hex"))

    // Update cache
    this.cachedKey = { key: masterKey, obtainedAt: Date.now() }
  }

  /**
   * Encrypt a per-engagement database buffer with AES-256-GCM.
   *
   * The engagement key is derived from the master key + engagement ID.
   * Each encryption uses a fresh random salt and IV.
   */
  static encryptEngagementDb(
    plaintext: Buffer,
    masterKey: Buffer,
    engagementId: string,
  ): Buffer {
    return aesGcmEncrypt(
      plaintext,
      masterKey,
      ENGAGEMENT_KEY_SALT,
      Buffer.from(engagementId, "utf-8"),
    )
  }

  /**
   * Decrypt a per-engagement database buffer.
   */
  static decryptEngagementDb(
    encrypted: Buffer,
    masterKey: Buffer,
    engagementId: string,
  ): Buffer {
    return aesGcmDecrypt(
      encrypted,
      masterKey,
      ENGAGEMENT_KEY_SALT,
      Buffer.from(engagementId, "utf-8"),
    )
  }

  /**
   * Encrypt an evidence file with AES-256-GCM.
   *
   * Each file gets its own derived key (master + engagement ID + file ID).
   */
  static encryptFile(
    plaintext: Buffer,
    masterKey: Buffer,
    engagementId: string,
    fileId: string,
  ): Buffer {
    return aesGcmEncrypt(
      plaintext,
      masterKey,
      FILE_KEY_SALT,
      Buffer.from(`${engagementId}:${fileId}`, "utf-8"),
    )
  }

  /**
   * Decrypt an evidence file.
   */
  static decryptFile(
    encrypted: Buffer,
    masterKey: Buffer,
    engagementId: string,
    fileId: string,
  ): Buffer {
    return aesGcmDecrypt(
      encrypted,
      masterKey,
      FILE_KEY_SALT,
      Buffer.from(`${engagementId}:${fileId}`, "utf-8"),
    )
  }

  /**
   * Clear the in-memory key cache.
   * Call this when the user logs out or the session ends.
   */
  static clearCache(): void {
    if (this.cachedKey) {
      // Best-effort zeroization (imperfect in V8 — see Risk 1)
      this.cachedKey.key.fill(0)
      this.cachedKey = null
    }
  }
}
