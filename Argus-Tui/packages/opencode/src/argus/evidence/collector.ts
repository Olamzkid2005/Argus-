import { mkdir, writeFile } from "fs/promises"
import { join } from "path"
import { createHash } from "crypto"
import type { EvidenceManifest, ArtifactEntry } from "./types"
import { Confidence } from "../planner/types"

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

  constructor(
    private baseDir: string,
    config?: Partial<CollectorConfig>,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config }
  }

  private async ensureDir(path: string): Promise<void> {
    await mkdir(path, { recursive: true })
  }

  private validateId(id: string, label: string): void {
    if (!/^[\w-]+$/.test(id)) throw new Error(`Invalid ${label}: ${id}`)
  }

  async saveRequest(engagementId: string, findingId: string, request: string): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "requests")
    await this.ensureDir(dir)
    const fileName = `request-${Date.now()}.txt`
    const filePath = join(dir, fileName)
    await writeFile(filePath, request)

    return {
      path: join("requests", fileName),
      hash: createHash("sha256").update(request).digest("hex"),
      type: "request" as const,
      size_bytes: Buffer.byteLength(request),
    }
  }

  async saveResponse(engagementId: string, findingId: string, response: string): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "responses")
    await this.ensureDir(dir)
    const fileName = `response-${Date.now()}.txt`
    const filePath = join(dir, fileName)
    await writeFile(filePath, response)

    return {
      path: join("responses", fileName),
      hash: createHash("sha256").update(response).digest("hex"),
      type: "response" as const,
      size_bytes: Buffer.byteLength(response),
    }
  }

  async captureScreenshot(engagementId: string, findingId: string, screenshotBuffer: Buffer): Promise<ArtifactEntry> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    const dir = join(this.baseDir, engagementId, "artifacts", findingId, "screenshots")
    await this.ensureDir(dir)
    const fileName = `screenshot-${Date.now()}.png`
    const filePath = join(dir, fileName)
    await writeFile(filePath, screenshotBuffer)

    return {
      path: join("screenshots", fileName),
      hash: createHash("sha256").update(screenshotBuffer).digest("hex"),
      type: "screenshot" as const,
      size_bytes: screenshotBuffer.length,
    }
  }

  async createPackage(engagementId: string, findingId: string, artifacts: ArtifactEntry[]): Promise<EvidenceManifest> {
    this.validateId(engagementId, "engagementId")
    this.validateId(findingId, "findingId")
    const manifest: EvidenceManifest = {
      package_id: findingId,
      engagement_id: engagementId,
      created_at: new Date().toISOString(),
      artifacts,
      package_hash: "",
    }

    const manifestStr = JSON.stringify(manifest, null, 2) + artifacts.map((a) => a.hash).join("")
    manifest.package_hash = createHash("sha256").update(manifestStr).digest("hex")

    const manifestDir = join(this.baseDir, engagementId, "artifacts", findingId)
    await this.ensureDir(manifestDir)
    await writeFile(join(manifestDir, "manifest.json"), JSON.stringify(manifest, null, 2))

    return manifest
  }
}
