import { mkdir, writeFile, readdir, stat, unlink, rmdir } from "fs/promises"
import { join, extname } from "path"
import { existsSync } from "fs"
import { createHash, randomBytes } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "./types"
import { computePackageHash } from "./hash"
import { Confidence } from "../shared/types"
import { EncryptedFileHandle } from "../storage/encrypted-file"
import { EncryptionManager } from "../storage/encryption"
import { parseHarDirectory, formatRequest, formatResponse } from "./har-parser"

interface CollectorConfig {
  retention_days: number
  max_engagement_size_mb: number
  capture_har: boolean
  capture_video: boolean
  capture_threshold: Confidence
}

const DEFAULT_CONFIG: CollectorConfig = {
  retention_days: 30,
  max_engagement_size_mb: 500,
  capture_har: false,
  capture_video: false,
  capture_threshold: Confidence.HIGH,
}

export class EvidenceCollector {
  private config: CollectorConfig
  /** When set, binary evidence files are encrypted at rest using this engagement's derived key. */
  private encryptionEngagementId: string | null = null
  /** Track engagements for which we've already warned about missing encryption key. */
  private _encryptionWarned: Set<string> = new Set()

  constructor(
    private baseDir: string,
    config?: Partial<CollectorConfig>,
    encryptionEngagementId?: string,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config }
    this.encryptionEngagementId = encryptionEngagementId ?? null
  }

  /**
   * Enable or disable encryption for this collector.
   * When set, binary files (screenshots, request/response text) are encrypted
   * at rest using AES-256-GCM with per-file derived keys.
   * Requires the master key to be loaded via EncryptionManager.getMasterKey().
   */
  setEncryption(engagementId: string): void {
    this.encryptionEngagementId = engagementId
  }

  /**
   * Check if encryption is active (engagement ID set + master key cached).
   * Logs a warning when encryption was requested (engagement ID set) but
   * the master key is not cached — this means data will be written as plaintext.
   */
  private _isEncrypted(): boolean {
    if (this.encryptionEngagementId === null) return false
    const key = EncryptionManager.getCachedMasterKey()
    if (key === null) {
      // Warn only once per engagement to avoid log spam
      if (!this._encryptionWarned.has(this.encryptionEngagementId)) {
        this._encryptionWarned.add(this.encryptionEngagementId)
        console.warn(
          `[Evidence] Encryption requested for engagement ${this.encryptionEngagementId} ` +
          "but master key is not cached — writing evidence as plaintext. " +
          "Set ARGUS_KEY_PASSPHRASE or call EncryptionManager.loadKey() before collecting evidence."
        )
      }
      return false
    }
    return true
  }

  /**
   * Get the master key for encryption. Returns null if not available.
   */
  private _getMasterKey(): Buffer | null {
    return EncryptionManager.getCachedMasterKey()
  }

  private async ensureDir(path: string): Promise<void> {
    await mkdir(path, { recursive: true })
  }

  private validateId(id: string, label: string): void {
    if (!/^[\w-]+$/.test(id)) throw new Error(`Invalid ${label}: ${id}`)
  }

  /**
   * Check the engagement storage limit before writing.
   * Returns true if within limit; false if over (caller should skip or compress).
   */
  async checkStorageLimit(engagementId: string): Promise<boolean> {
    this.validateId(engagementId, "engagementId")
    const engDir = join(this.baseDir, engagementId)
    if (!existsSync(engDir)) return true

    let totalBytes = 0
    try {
      // recursive + withFileTypes requires Node 18.17+. Bun supports it natively.
      // Argus runs under Bun, so this is not a compatibility concern in practice.
      const entries = await readdir(engDir, { recursive: true, withFileTypes: true })
      for (const entry of entries) {
        if (entry.isFile()) {
          const filePath = join(entry.parentPath, entry.name)
          totalBytes += (await stat(filePath)).size
        }
      }
    } catch (e) {
      console.warn(`[Evidence] Failed to check storage limit for ${engagementId}: ${(e as Error).message}`)
      return false
    }

    const maxBytes = this.config.max_engagement_size_mb * 1024 * 1024
    const warnThreshold = maxBytes * 0.8
    const isOver = totalBytes >= maxBytes

    if (isOver) {
      console.warn(`[Evidence] Engagement ${engagementId} exceeds storage limit (${(totalBytes / 1024 / 1024).toFixed(1)}MB / ${this.config.max_engagement_size_mb}MB)`)
    } else if (totalBytes >= warnThreshold) {
      console.warn(`[Evidence] Engagement ${engagementId} at ${((totalBytes / maxBytes) * 100).toFixed(0)}% of storage limit`)
    }

    return !isOver
  }

  /**
   * Prune old or oversized artifacts: compress PNG screenshots when near limit,
   * delete files older than retention_days for completed engagements.
   */
  async pruneEngagement(engagementId: string, retentionDays?: number): Promise<number> {
    this.validateId(engagementId, "engagementId")
    const engDir = join(this.baseDir, engagementId, "artifacts")
    if (!existsSync(engDir)) return 0

    const cutoff = Date.now() - (retentionDays ?? this.config.retention_days) * 86400000
    let pruned = 0

    try {
      const findingDirs = await readdir(engDir, { withFileTypes: true })
      for (const findingDir of findingDirs) {
        if (!findingDir.isDirectory()) continue
        const findingPath = join(engDir, findingDir.name)

        // Walk each artifact type directory (screenshots/, requests/, responses/)
        const typeDirs = await readdir(findingPath, { withFileTypes: true })
        for (const typeDir of typeDirs) {
          if (!typeDir.isDirectory()) continue
          const typePath = join(findingPath, typeDir.name)
          const files = await readdir(typePath, { withFileTypes: true })

          for (const file of files) {
            if (!file.isFile()) continue
            const filePath = join(typePath, file.name)

            try {
              const fileStat = await stat(filePath)
              if (fileStat.mtimeMs <= cutoff) {
                await unlink(filePath)
                pruned++
              }
            } catch (e) {
              console.warn(`[Evidence] Failed to stat/unlink ${filePath}: ${(e as Error).message}`)
            }
          }
        }

        // Clean up empty directories
        for (const typeDir of typeDirs) {
          if (!typeDir.isDirectory()) continue
          const typePath = join(findingPath, typeDir.name)
          try {
            const remaining = await readdir(typePath)
            if (remaining.length === 0) {
              await rmdir(typePath)
            }
          } catch (e) {
            console.warn(`[Evidence] Failed to remove empty dir ${typePath}: ${(e as Error).message}`)
          }
        }
      }
    } catch (e) {
      console.warn(`[Evidence] pruneEngagement error: ${(e as Error).message}`)
      return pruned
    }

    return pruned
  }

  async saveRequest(engagementId: string, findingId: string, request: string): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    if (!(await this.checkStorageLimit(engagementId))) throw new Error(`Storage limit exceeded for engagement ${engagementId}`)
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "requests")
    await this.ensureDir(dir)
    const fileName = `request-${Date.now()}-${randomBytes(4).toString("hex")}.txt`
    const filePath = join(dir, fileName)
    const plaintext = Buffer.from(request, "utf-8")
    const relativePath = join("requests", fileName)

    if (this._isEncrypted()) {
      const masterKey = this._getMasterKey()!
      const fileId = EncryptedFileHandle.fileIdFromPath(relativePath)
      EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, this.encryptionEngagementId!, fileId)
    } else {
      await writeFile(filePath, plaintext)
    }

    return {
      path: relativePath,
      hash: createHash("sha256").update(plaintext).digest("hex"),
      type: "request" as const,
      size_bytes: plaintext.length,
    }
  }

  async saveResponse(engagementId: string, findingId: string, response: string): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    if (!(await this.checkStorageLimit(engagementId))) throw new Error(`Storage limit exceeded for engagement ${engagementId}`)
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "responses")
    await this.ensureDir(dir)
    const fileName = `response-${Date.now()}-${randomBytes(4).toString("hex")}.txt`
    const filePath = join(dir, fileName)
    const plaintext = Buffer.from(response, "utf-8")
    const relativePath = join("responses", fileName)

    if (this._isEncrypted()) {
      const masterKey = this._getMasterKey()!
      const fileId = EncryptedFileHandle.fileIdFromPath(relativePath)
      EncryptedFileHandle.writeEncrypted(filePath, plaintext, masterKey, this.encryptionEngagementId!, fileId)
    } else {
      await writeFile(filePath, plaintext)
    }

    return {
      path: relativePath,
      hash: createHash("sha256").update(plaintext).digest("hex"),
      type: "response" as const,
      size_bytes: plaintext.length,
    }
  }

  async captureScreenshot(engagementId: string, findingId: string, screenshotBuffer: Buffer): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    if (!(await this.checkStorageLimit(engagementId))) throw new Error(`Storage limit exceeded for engagement ${engagementId}`)
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "screenshots")
    await this.ensureDir(dir)
    const fileName = `screenshot-${Date.now()}-${randomBytes(4).toString("hex")}.png`
    const filePath = join(dir, fileName)
    const relativePath = join("screenshots", fileName)

    if (this._isEncrypted()) {
      const masterKey = this._getMasterKey()!
      const fileId = EncryptedFileHandle.fileIdFromPath(relativePath)
      EncryptedFileHandle.writeEncrypted(filePath, screenshotBuffer, masterKey, this.encryptionEngagementId!, fileId)
    } else {
      await writeFile(filePath, screenshotBuffer)
    }

    return {
      path: relativePath,
      hash: createHash("sha256").update(screenshotBuffer).digest("hex"),
      type: "screenshot" as const,
      size_bytes: screenshotBuffer.length,
    }
  }

  /**
   * Ingest HAR files from a directory, saving each request/response pair
   * through the EvidenceCollector and returning all created artifact entries.
   *
   * Uses the har-parser module to read and parse Playwright HAR files,
   * then saves the request and response data as text artifacts. The resulting
   * artifacts can be passed directly to createPackage().
   *
   * @param engagementId - The engagement these artifacts belong to.
   * @param findingId - The finding these artifacts are evidence for.
   * @param harDir - Directory containing .har files from Playwright's recordHar.
   * @returns Array of ArtifactEntry created (empty if no HAR files found or on error).
   */
  async ingestHarFiles(engagementId: string, findingId: string, harDir: string): Promise<ArtifactEntry[]> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")

    if (!existsSync(harDir)) {
      return []
    }

    if (!(await this.checkStorageLimit(engagementId))) {
      console.warn(`[Evidence] Storage limit exceeded for ${engagementId} — skipping HAR ingestion`)
      return []
    }

    const entries = parseHarDirectory(harDir)
    if (entries.length === 0) {
      return []
    }

    const artifacts: ArtifactEntry[] = []
    let saved = 0

    for (const entry of entries) {
      try {
        const reqText = formatRequest(entry)
        const resText = formatResponse(entry)

        const reqArtifact = await this.saveRequest(engagementId, findingId, reqText)
        artifacts.push(reqArtifact)

        const resArtifact = await this.saveResponse(engagementId, findingId, resText)
        artifacts.push(resArtifact)

        saved++
      } catch (e) {
        console.warn(`[Evidence] Failed to save HAR entry for ${entry.url}: ${(e as Error).message}`)
      }
    }

    console.log(`[Evidence] Ingested ${saved} HAR entries from ${harDir} for finding ${findingId}`)
    return artifacts
  }

  async createPackage(engagementId: string, findingId: string, artifacts: ArtifactEntry[]): Promise<EvidenceManifest> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    if (!(await this.checkStorageLimit(engagementId))) throw new Error(`Storage limit exceeded for engagement ${engagementId}`)
    const manifest: EvidenceManifest = {
      package_id: findingId,
      engagement_id: engagementId,
      created_at: new Date().toISOString(),
      artifacts,
      package_hash: "",
    }

    manifest.package_hash = computePackageHash(manifest, artifacts)

    const manifestDir = join(this.baseDir, engagementId, "artifacts", findingId)
    await this.ensureDir(manifestDir)
    await writeFile(join(manifestDir, "manifest.json"), JSON.stringify(manifest, null, 2))

    return manifest
  }
}
