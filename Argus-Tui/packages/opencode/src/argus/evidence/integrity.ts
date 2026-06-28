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

export interface VerifyPackageOptions {
  /**
   * Master key for decrypting encrypted evidence files.
   * If provided, artifact files are decrypted before hash verification.
   * The SHA-256 hash in the manifest is computed on the PLAINTEXT,
   * so files must be decrypted before hashing for correct integrity check.
   */
  masterKey?: Buffer
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

  const computedHash = computePackageHash(manifest, manifest.artifacts)
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
