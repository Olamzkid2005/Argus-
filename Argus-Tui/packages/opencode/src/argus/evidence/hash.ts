import { createHash, createHmac } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "./types"

/**
 * Compute the package_hash for an EvidenceManifest.
 *
 * When an hmacKey is provided, uses HMAC-SHA256 for tamper-evident signing.
 * Without an hmacKey, uses plain SHA-256 (backward compatible).
 *
 * Hash = (HMAC-)SHA256(JSON.stringify(manifest, null, 2) + artifact hashes concatenated)
 * The manifest's own package_hash is zeroed out before stringifying so the result
 * is deterministic regardless of the stored hash.
 *
 * Shared by ArtifactStore, EvidenceCollector, and verifyPackage.
 */
export function computePackageHash(
  manifest: EvidenceManifest,
  artifacts: ArtifactEntry[],
  hmacKey?: string | Buffer,
): string {
  const sortedManifest = Object.keys({ ...manifest, package_hash: "" })
    .sort()
    .reduce<Record<string, unknown>>((acc, key) => {
      acc[key] = (manifest as unknown as Record<string, unknown>)[key] ?? ""
      return acc
    }, {})
  sortedManifest.package_hash = ""
  const manifestStr =
    JSON.stringify(sortedManifest, null, 2) +
    artifacts.map((a) => a.hash).join("")

  if (hmacKey) {
    return createHmac("sha256", hmacKey).update(manifestStr).digest("hex")
  }
  return createHash("sha256").update(manifestStr).digest("hex")
}
