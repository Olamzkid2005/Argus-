import { readFileSync, existsSync, createReadStream } from "fs"
import { createHash } from "crypto"
import { join } from "path"
import type { EvidenceManifest, IntegrityReport } from "./types"
import { computePackageHash } from "./hash"
import { EncryptedFileHandle } from "../storage/encrypted-file"

function hashFile(filePath: string): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const hash = createHash("sha256")
    const stream = createReadStream(filePath)
    stream.on("data", (chunk) => hash.update(chunk))
    stream.on("end", () => resolve(hash.digest("hex")))
    stream.on("error", (err) => reject(err))
  })
}

/**
 * Validate that an artifact path is safe — does not escape the package directory.
 *
 * On Windows, path.join() produces paths with backslash (\\) separators,
 * which are valid and safe. The check normalizes backslashes to forward slashes
 * so that path traversal detection works consistently across platforms.
 *
 * Rejects paths containing "..", absolute paths, null bytes, or forbidden
 * Windows filename characters.
 */
function isValidArtifactPath(artifactPath: string): boolean {
  if (!artifactPath || typeof artifactPath !== "string") return false
  // Normalize backslashes to forward slashes for consistent path traversal checks
  const normalized = artifactPath.replace(/\\/g, "/")
  if (normalized.includes("..")) return false
  if (normalized.startsWith("/")) return false
  if (normalized.includes("\0")) return false
  if (/[<>"|?*]/.test(normalized)) return false
  return true
}

export interface VerifyPackageOptions {
  /**
   * Master key for decrypting encrypted evidence files.
   * If provided, artifact files are decrypted before hash verification.
   * The SHA-256 hash in the manifest is computed on the PLAINTEXT,
   * so files must be decrypted before hashing for correct integrity check.
   */
  masterKey?: Buffer
  /**
   * HMAC key for verifying tamper-evident package hashes.
   * If provided, computePackageHash uses HMAC-SHA256 instead of plain SHA-256.
   * Must match the key used when the evidence package was created.
   */
  hmacKey?: string | Buffer
}

export async function verifyPackage(
  baseDir: string,
  engagementId: string,
  packageId: string,
  options?: VerifyPackageOptions,
): Promise<IntegrityReport> {
  if (!/^[\w-]+$/.test(packageId)) {
    return { valid: false, packageId, manifestHash: "", computedHash: "", errors: ["Invalid package ID"] }
  }

  const manifestPath = join(baseDir, engagementId, "artifacts", packageId, "manifest.json")

  if (!existsSync(manifestPath)) {
    return {
      valid: false,
      packageId,
      manifestHash: "",
      computedHash: "",
      errors: ["Manifest file not found"],
    }
  }

  let manifest: EvidenceManifest
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf-8"))
  } catch (err) {
    return {
      valid: false,
      packageId,
      manifestHash: "",
      computedHash: "",
      errors: [`Corrupt manifest JSON: ${(err as Error).message}`],
    }
  }

  const errors: string[] = []

  // Stream-based hash for large files to avoid loading entire artifact into memory
  for (const artifact of manifest.artifacts) {
    // Reject path traversal — artifact.path must not escape the package directory
    if (!isValidArtifactPath(artifact.path)) {
      errors.push(`Invalid artifact path: ${artifact.path} — path traversal blocked`)
      continue
    }
    const artifactPath = join(baseDir, engagementId, "artifacts", packageId, artifact.path)
    if (!existsSync(artifactPath)) {
      errors.push(`Artifact missing: ${artifact.path}`)
      continue
    }

    let actualHash: string
    if (options?.masterKey) {
      // Encrypted file: decrypt first, then hash the plaintext
      const fileId = EncryptedFileHandle.fileIdFromPath(artifact.path)
      try {
        const plaintext = EncryptedFileHandle.readEncrypted(
          artifactPath,
          options.masterKey,
          engagementId,
          fileId,
        )
        actualHash = createHash("sha256").update(plaintext).digest("hex")
      } catch {
        errors.push(`Failed to decrypt ${artifact.path} — file may be corrupted or key may be wrong`)
        continue
      }
    } else {
      actualHash = await hashFile(artifactPath)
    }

    if (actualHash !== artifact.hash) {
      errors.push(`Hash mismatch for ${artifact.path}: expected ${artifact.hash}, got ${actualHash}`)
    }
  }

  const computedHash = computePackageHash(manifest, manifest.artifacts, options?.hmacKey)
  const hashValid = computedHash === manifest.package_hash

  if (!hashValid) {
    errors.push("Package hash does not match computed hash")
  }

  return {
    valid: errors.length === 0,
    packageId,
    manifestHash: manifest.package_hash,
    computedHash,
    errors,
  }
}
