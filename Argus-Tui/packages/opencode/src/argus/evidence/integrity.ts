import { readFileSync, existsSync, createReadStream } from "fs"
import { join } from "path"
import { createHash } from "crypto"
import type { EvidenceManifest, IntegrityReport } from "./types"

function hashFileSync(filePath: string): string {
  const hash = createHash("sha256")
  const content = readFileSync(filePath)
  hash.update(content)
  return hash.digest("hex")
}

export function verifyPackage(baseDir: string, packageId: string): IntegrityReport {
  if (!/^[\w-]+$/.test(packageId)) {
    return { valid: false, packageId, manifestHash: "", computedHash: "", errors: ["Invalid package ID"] }
  }

  const manifestPath = join(baseDir, "artifacts", packageId, "manifest.json")

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
    const actualHash = hashFileSync(artifactPath)
    if (actualHash !== artifact.hash) {
      errors.push(`Hash mismatch for ${artifact.path}: expected ${artifact.hash}, got ${actualHash}`)
    }
  }

  const manifestStr = JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
    manifest.artifacts.map((a) => a.hash).join("")
  const computedHash = createHash("sha256").update(manifestStr).digest("hex")
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
