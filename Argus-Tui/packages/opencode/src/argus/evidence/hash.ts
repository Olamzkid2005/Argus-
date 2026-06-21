import { createHash } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "./types"

/**
 * Compute the package_hash for an EvidenceManifest.
 *
 * Hash = sha256(JSON.stringify(manifest, null, 2) + artifact hashes concatenated).
 * The manifest's own package_hash is zeroed out before stringifying so the result
 * is deterministic regardless of the stored hash.
 *
 * Shared by ArtifactStore, EvidenceCollector, and verifyPackage.
 */
export function computePackageHash(
  manifest: EvidenceManifest,
  artifacts: ArtifactEntry[],
): string {
  const manifestStr =
    JSON.stringify({ ...manifest, package_hash: "" }, null, 2) +
    artifacts.map((a) => a.hash).join("")
  return createHash("sha256").update(manifestStr).digest("hex")
}
