import { readFileSync, existsSync } from "fs"
import { join } from "path"
import { createHash } from "crypto"
import { EvidenceManifest, IntegrityReport } from "./types"

export function verifyPackage(baseDir: string, packageId: string): IntegrityReport {
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

  const manifest: EvidenceManifest = JSON.parse(readFileSync(manifestPath, "utf-8"))

  const errors: string[] = []

  for (const artifact of manifest.artifacts) {
    const artifactPath = join(baseDir, "artifacts", packageId, artifact.path)
    if (!existsSync(artifactPath)) {
      errors.push(`Artifact missing: ${artifact.path}`)
      continue
    }
    const content = readFileSync(artifactPath)
    const actualHash = createHash("sha256").update(content).digest("hex")
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
