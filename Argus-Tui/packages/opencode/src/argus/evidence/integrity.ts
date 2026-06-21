import { readFileSync, existsSync, createReadStream } from "fs"
import { createHash } from "crypto"
import { join } from "path"
import type { EvidenceManifest, IntegrityReport } from "./types"
import { computePackageHash } from "./hash"

function hashFile(filePath: string): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const hash = createHash("sha256")
    const stream = createReadStream(filePath)
    stream.on("data", (chunk) => hash.update(chunk))
    stream.on("end", () => resolve(hash.digest("hex")))
    stream.on("error", (err) => reject(err))
  })
}

export async function verifyPackage(baseDir: string, engagementId: string, packageId: string): Promise<IntegrityReport> {
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
    const artifactPath = join(baseDir, "artifacts", packageId, artifact.path)
    if (!existsSync(artifactPath)) {
      errors.push(`Artifact missing: ${artifact.path}`)
      continue
    }
    const actualHash = await hashFile(artifactPath)
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
