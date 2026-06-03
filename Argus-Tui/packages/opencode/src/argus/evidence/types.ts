export type ArtifactType = "screenshot" | "request" | "response" | "har" | "log"

export interface ArtifactEntry {
  path: string
  hash: string
  type: ArtifactType
  size_bytes: number
}

export interface EvidenceManifest {
  package_id: string
  engagement_id: string
  created_at: string
  artifacts: ArtifactEntry[]
  package_hash: string
}

export interface IntegrityReport {
  valid: boolean
  packageId: string
  manifestHash: string
  computedHash: string
  errors: string[]
}
