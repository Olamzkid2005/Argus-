import { readFile, readdir, writeFile, mkdir, stat } from "fs/promises"
import { join, dirname } from "path"
import { existsSync } from "fs"
import { createHash } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "./types"

/**
 * ArtifactStore — filesystem-backed evidence storage with manifest tracking.
 *
 * Stores binary artifacts under `~/.argus/engagements/ENG-{id}/artifacts/`
 * with per-package manifest.json for integrity verification.
 */
export class ArtifactStore {
  constructor(private baseDir: string) {}

  private validateId(id: string, label: string): void {
    if (!/^[\w-]+$/.test(id)) throw new Error(`Invalid ${label}: ${id}`)
  }

  private async ensureDir(path: string): Promise<void> {
    await mkdir(path, { recursive: true })
  }

  /**
   * Create an evidence package directory and write the manifest.
   * Returns the package directory path.
   */
  async createPackage(
    engagementId: string,
    findingId: string,
    artifacts: ArtifactEntry[],
  ): Promise<EvidenceManifest> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")

    const manifest: EvidenceManifest = {
      package_id: findingId,
      engagement_id: engagementId,
      created_at: new Date().toISOString(),
      artifacts,
      package_hash: "",
    }

    const manifestStr =
      JSON.stringify(manifest, null, 2) +
      artifacts.map((a) => a.hash).join("")
    manifest.package_hash = createHash("sha256")
      .update(manifestStr)
      .digest("hex")

    const pkgDir = join(this.baseDir, engagementId, "artifacts", findingId)
    await this.ensureDir(pkgDir)
    await writeFile(
      join(pkgDir, "manifest.json"),
      JSON.stringify(manifest, null, 2),
    )

    return manifest
  }

  /**
   * Get a package's manifest for a given finding.
   * Returns null if the package does not exist.
   */
  async getPackage(
    engagementId: string,
    findingId: string,
  ): Promise<EvidenceManifest | null> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")

    const manifestPath = join(
      this.baseDir,
      engagementId,
      "artifacts",
      findingId,
      "manifest.json",
    )
    if (!existsSync(manifestPath)) return null

    const content = await readFile(manifestPath, "utf-8")
    return JSON.parse(content) as EvidenceManifest
  }

  /**
   * List all available packages for an engagement.
   * Returns an array of manifests (or partial summaries if manifests can't be read).
   */
  async listPackages(
    engagementId: string,
  ): Promise<EvidenceManifest[]> {
    this.validateId(engagementId, "engagementId")

    const artifactsDir = join(this.baseDir, engagementId, "artifacts")
    if (!existsSync(artifactsDir)) return []

    const entries = await readdir(artifactsDir, { withFileTypes: true })
    const results: EvidenceManifest[] = []

    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const manifest = await this.getPackage(engagementId, entry.name)
      if (manifest) results.push(manifest)
    }

    return results
  }

  /**
   * Delete an entire evidence package directory.
   */
  async deletePackage(
    engagementId: string,
    findingId: string,
  ): Promise<boolean> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")

    const pkgDir = join(this.baseDir, engagementId, "artifacts", findingId)
    if (!existsSync(pkgDir)) return false

    // Recursive directory removal (fs.rm with recursive)
    const { rm } = await import("fs/promises")
    await rm(pkgDir, { recursive: true, force: true })
    return true
  }

  /**
   * Get the total size of all packages for an engagement.
   */
  async getEngagementSize(engagementId: string): Promise<number> {
    this.validateId(engagementId, "engagementId")

    const artifactsDir = join(this.baseDir, engagementId, "artifacts")
    if (!existsSync(artifactsDir)) return 0

    let totalBytes = 0
    const entries = await readdir(artifactsDir, {
      recursive: true,
      withFileTypes: true,
    })
    for (const entry of entries) {
      if (entry.isFile()) {
        try {
          totalBytes += (await stat(join(entry.parentPath, entry.name))).size
        } catch {
          // skip unreadable
        }
      }
    }
    return totalBytes
  }
}
