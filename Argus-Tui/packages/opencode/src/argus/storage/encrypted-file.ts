/**
 * Encrypted File Handle — transparent encrypt/decrypt for evidence files (Layer 3)
 *
 * Encrypts individual evidence files (screenshots, HAR logs, request/response text)
 * using AES-256-GCM with per-file derived keys. Each file gets a unique key derived
 * from the master key + engagement ID + relative file path via HKDF.
 *
 * ── On-disk format (same as encrypted-db) ──
 *   [VERSION:1][SALT:16][IV:12][CIPHERTEXT...][AUTH TAG:16]
 *
 * ── Key derivation ──
 *   fileKey = HKDF-SHA256(masterKey, salt="argus-file-v1", info=engagementId + ":" + fileId)
 *
 * ── Integration ──
 *   Used by EvidenceCollector (write path) and verifyPackage (read/integrity path).
 *   Manifests remain plaintext for discovery. Only binary file content is encrypted.
 */
import { readFileSync, writeFileSync, renameSync, unlinkSync } from "node:fs"
import { EncryptionManager } from "./encryption"

/** Suffix for atomically-written temp files */
const ENC_TMP_SUFFIX = ".encrypting"

/**
 * EncryptedFileHandle — static utility for encrypting/decrypting individual evidence files.
 */
export class EncryptedFileHandle {
  /**
   * Encrypt data and write it atomically to disk.
   *
   * Writes to a `.encrypting` temp file first, then renames atomically.
   * The fileId is typically the relative path within the artifact directory
   * (e.g., "screenshots/screenshot-1234.png").
   *
   * @param filePath  Absolute path to write the encrypted file to
   * @param plaintext Raw data to encrypt (before encryption)
   * @param masterKey 32-byte master encryption key
   * @param engagementId  Engagement ID (e.g., "ENG-abc123")
   * @param fileId  Unique file identifier for key derivation (e.g., relative path)
   */
  static writeEncrypted(
    filePath: string,
    plaintext: Buffer,
    masterKey: Buffer,
    engagementId: string,
    fileId: string,
  ): void {
    const ciphertext = EncryptionManager.encryptFile(plaintext, masterKey, engagementId, fileId)

    // Atomic write: temp file → rename
    const tmpPath = filePath + ENC_TMP_SUFFIX
    writeFileSync(tmpPath, ciphertext, { mode: 0o600 })
    renameSync(tmpPath, filePath)
  }

  /**
   * Read an encrypted file from disk and decrypt it.
   *
   * @param filePath  Absolute path to the encrypted file
   * @param masterKey 32-byte master encryption key
   * @param engagementId  Engagement ID
   * @param fileId  Unique file identifier (must match the one used during write)
   * @returns Decrypted plaintext Buffer
   */
  static readEncrypted(
    filePath: string,
    masterKey: Buffer,
    engagementId: string,
    fileId: string,
  ): Buffer {
    const ciphertext = readFileSync(filePath)
    return EncryptionManager.decryptFile(ciphertext, masterKey, engagementId, fileId)
  }

  /**
   * Delete an encrypted file and any residual temp file.
   * Best-effort — does not throw on failure.
   */
  static deleteEncrypted(filePath: string): void {
    try { unlinkSync(filePath) } catch { /* best-effort */ }
    try { unlinkSync(filePath + ENC_TMP_SUFFIX) } catch { /* best-effort */ }
  }

  /**
   * Check if a file is likely encrypted by inspecting its header.
   * Returns true if the first byte has the VERSION_BYTE flag (0x01).
   * This is a heuristic — plaintext SQLite DBs or other binary files
   * could coincidentally start with 0x01.
   */
  static isEncryptedFile(filePath: string): boolean {
    try {
      const fd = readFileSync(filePath)
      return fd.length > 0 && (fd[0] & 0x01) === 0x01
    } catch {
      return false
    }
  }

  /**
   * Derive a deterministic file ID from a relative path.
   * This ensures the same path always produces the same file ID
   * for consistent key derivation across write and read.
   */
  static fileIdFromPath(relativePath: string): string {
    return relativePath.replace(/\\/g, "/")
  }
}
